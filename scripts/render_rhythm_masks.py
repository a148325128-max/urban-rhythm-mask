#!/usr/bin/env python3
"""Render synchronized still-image lighting masks from an explicit JSON timeline."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def smooth(x):
    x = max(0., min(1., x))
    return x * x * (3. - 2. * x)


def envelope(t, event):
    start = event['on']
    end = event.get('off', float('inf'))
    if t < start or t >= end:
        return 0.
    attack = event.get('attack', .025)
    release = event.get('release', .025)
    a = smooth((t - start) / attack) if attack > 0 else 1.
    if math.isfinite(end) and release > 0:
        a *= smooth((end - t) / release)
    return a * event.get('strength', 1.)


class Renderer:
    def __init__(self, config_path, width=None, height=None):
        self.config_path = Path(config_path).resolve()
        self.root = self.config_path.parent
        self.cfg = json.loads(self.config_path.read_text())
        if self.cfg.get('time_domain') != 'output_seconds':
            raise ValueError('Timeline must explicitly use output_seconds')
        self.w = width or self.cfg['width']
        self.h = height or self.cfg['height']
        self.fps = self.cfg['fps']
        self.frames = round(self.cfg['duration'] * self.fps)
        self.duration = self.frames / self.fps
        if self.w % 2 or self.h % 2 or self.fps <= 0 or self.frames <= 0:
            raise ValueError('Use positive FPS, duration, and even image dimensions')
        self.scenes = []
        self.evidence = []
        last_end = 0.
        for spec in self.cfg['scenes']:
            if abs(spec['start'] - last_end) > .00001 or spec['end'] <= spec['start']:
                raise ValueError('Scenes must form a continuous non-overlapping timeline')
            last_end = spec['end']
            source = (self.root / spec['source']).resolve()
            im = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if im is None:
                raise ValueError(f'Cannot read {source}')
            im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
            sh, sw = im.shape[:2]
            # Match the source ratio; do not silently stretch a new source.
            if abs((sw / sh) / (self.w / self.h) - 1) > .015:
                raise ValueError('Source aspect ratio differs; prepare its crop and masks together')
            im = cv2.resize(im, (self.w, self.h), interpolation=cv2.INTER_LANCZOS4)
            bright = im.astype(np.float32)
            gray = cv2.cvtColor(im, cv2.COLOR_RGB2GRAY).astype(np.float32)
            sat = spec.get('dark_saturation', .02)
            base = (gray[..., None] * (1 - sat) + bright * sat) * spec.get('dark_gain', .16)
            masks = {}
            for m in spec['masks']:
                if m['id'] in masks:
                    raise ValueError('Duplicate mask ID')
                canvas = np.zeros((self.h, self.w), dtype=np.uint8)
                if 'alpha_file' in m:
                    alpha_path = (self.root / m['alpha_file']).resolve()
                    alpha = cv2.imread(str(alpha_path), cv2.IMREAD_GRAYSCALE)
                    if alpha is None or alpha.shape != (sh,sw):
                        raise ValueError('Alpha file must match its uncropped source dimensions')
                    canvas = cv2.resize(alpha,(self.w,self.h),interpolation=cv2.INTER_LINEAR)
                else:
                    poly = np.asarray(m['polygon'], dtype=float)
                    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all():
                        raise ValueError('A mask polygon needs at least three finite XY points')
                    poly = np.rint(poly * np.array([self.w / sw, self.h / sh])).astype(np.int32)
                    cv2.fillPoly(canvas, [poly], 255)
                    for hole in m.get('holes', []):
                        hp = np.asarray(hole, dtype=float)
                        if hp.ndim != 2 or hp.shape[1] != 2 or len(hp)<3 or not np.isfinite(hp).all():
                            raise ValueError('A mask hole requires at least three finite XY points')
                        hp = np.rint(hp * np.array([self.w / sw, self.h / sh])).astype(np.int32)
                        cv2.fillPoly(canvas, [hp], 0)
                feather = m.get('feather_px', .8) * self.w / sw
                if feather > 0:
                    canvas = cv2.GaussianBlur(canvas, (0, 0), feather)
                nz = cv2.findNonZero(canvas)
                if nz is None:
                    raise ValueError('Mask is empty')
                x, y, w, h = cv2.boundingRect(nz)
                masks[m['id']] = (x, y, w, h, canvas[y:y+h, x:x+w].astype(np.float32) / 255.)
            for e in spec['events']:
                if not spec['start'] <= e['on'] < e.get('off', spec['end']) <= spec['end']:
                    raise ValueError(f'Event outside scene: {e}')
                if any(mid not in masks for mid in e['masks']):
                    raise ValueError('Event references unknown mask')
            self.scenes.append(dict(spec=spec, base=base, bright=bright, delta=bright-base, masks=masks))
            self.evidence.append(dict(id=spec['id'], source=str(source), source_size=[sw, sh],
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(), masks=len(masks), events=len(spec['events'])))
        if abs(last_end - self.duration) > 1 / self.fps / 2:
            raise ValueError('Final scene end differs from output duration')
        self.label = self.make_label(self.cfg.get('label', ''))

    def make_label(self, text):
        layer = Image.new('RGBA', (self.w, self.h), (0, 0, 0, 0))
        if not text:
            return np.asarray(layer)
        fonts = ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Light.ttc',
                 '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
        font_path = next((p for p in fonts if Path(p).exists()), None)
        font = ImageFont.truetype(font_path, max(14, round(self.w * .019))) if font_path else ImageFont.load_default()
        draw = ImageDraw.Draw(layer)
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = box[2]-box[0], box[3]-box[1]
        x = (self.w - tw) // 2
        y = int(self.h * .938)
        draw.rounded_rectangle((x-14, y-9, x+tw+14, y+th+14), 8, fill=(0, 0, 0, 130))
        draw.text((x, y-box[1]), text, font=font, fill=(245, 245, 245, 225))
        return np.array(layer)

    def frame(self, t, label=True, return_alpha=False):
        scene = next((s for s in self.scenes if s['spec']['start'] <= t < s['spec']['end']), None)
        if scene is None:
            raise ValueError('Frame time lies outside timeline')
        a = np.zeros((self.h, self.w), dtype=np.float32)
        for e in scene['spec']['events']:
            strength = envelope(t, e)
            if strength <= 0:
                continue
            for mid in e['masks']:
                x, y, w, h, m = scene['masks'][mid]
                roi = a[y:y+h, x:x+w]
                np.maximum(roi, m * strength, out=roi)
        full = scene['spec'].get('full_reveal')
        if full is not None:
            np.maximum(a, smooth((t-full['on']) / full.get('attack', .06)), out=a)
        np.clip(a, 0, 1, out=a)
        rgb = np.clip(scene['base'] + scene['delta'] * a[..., None], 0, 255).astype(np.uint8)
        if label and self.cfg.get('label'):
            la = self.label[..., 3:4].astype(np.float32) / 255
            rgb = (rgb * (1-la) + self.label[..., :3] * la).astype(np.uint8)
        return (rgb, a, scene) if return_alpha else rgb

    def diagnostics(self, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        for scene in self.scenes:
            im = scene['bright'].astype(np.uint8).copy()
            for mid, (x, y, w, h, mask) in scene['masks'].items():
                contour, _ = cv2.findContours((mask > .5).astype('uint8'), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in contour:
                    c += np.array([[[x,y]]])
                cv2.drawContours(im, contour, -1, (70, 250, 140), max(1, self.w//500))
                cv2.putText(im, mid, (x, max(20,y)), cv2.FONT_HERSHEY_SIMPLEX, self.w/1500, (255,90,90), 2)
                # Store full-size grayscale alpha files for reuse outside this renderer.
                canvas = np.zeros((self.h,self.w), dtype=np.uint8)
                canvas[y:y+h,x:x+w] = np.rint(mask*255).astype(np.uint8)
                Image.fromarray(canvas).save(folder / f"{scene['spec']['id']}_{mid}.png")
            Image.fromarray(im).save(folder / f"{scene['spec']['id']}_标定.jpg", quality=92)


def encode(renderer, output, overwrite=False, audio=True):
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(output)
    temp = output.with_name(output.stem + '.rendering.mp4')
    if temp.exists():
        raise FileExistsError(temp)
    cmd = ['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-f','rawvideo','-pix_fmt','rgb24',
           '-s',f'{renderer.w}x{renderer.h}','-r',str(renderer.fps),'-i','pipe:0']
    audio_path = renderer.cfg.get('audio') if audio else None
    if audio_path:
        cmd += ['-ss',str(renderer.cfg.get('audio_start',0)), '-i',str((renderer.root/audio_path).resolve()),
                '-map','0:v:0','-map','1:a:0', '-af',f'afade=t=in:d=0.03,afade=t=out:st={renderer.duration-.18}:d=0.18',
                '-c:a','aac','-b:a','192k']
    else:
        cmd += ['-an']
    cmd += ['-t',str(renderer.duration),'-c:v','libx264','-preset','fast','-crf','18',
            '-vf','scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
            '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',
            '-movflags','+faststart',str(temp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i in range(renderer.frames):
            proc.stdin.write(renderer.frame(i/renderer.fps).tobytes())
            if i % renderer.fps == 0:
                print(f'{i}/{renderer.frames}', flush=True)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError('FFmpeg encoding failed')
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams',
                                                   '-show_format','-of','json',str(temp)]))
        video = next(s for s in probe['streams'] if s['codec_type']=='video')
        if int(video['nb_read_frames']) != renderer.frames or (video['width'],video['height'])!=(renderer.w,renderer.h):
            raise RuntimeError('Output frame count or dimensions differ')
        if abs(float(probe['format']['duration'])-renderer.duration) > .08:
            raise RuntimeError('Output duration differs')
        if audio_path and not any(s['codec_type']=='audio' for s in probe['streams']):
            raise RuntimeError('Output audio missing')
        temp.replace(output)
        report = dict(output=str(output), width=renderer.w, height=renderer.h, frames=renderer.frames,
                      fps=renderer.fps, duration=renderer.duration, audio=bool(audio_path),
                      source_evidence=renderer.evidence, config_sha256=hashlib.sha256(renderer.config_path.read_bytes()).hexdigest())
        output.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False),flush=True)
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True); p.add_argument('--output')
    p.add_argument('--size',help='Even WxH, same aspect ratio as prepared inputs')
    p.add_argument('--stills',help='Comma-separated output timeline seconds')
    p.add_argument('--qa-dir'); p.add_argument('--overwrite',action='store_true')
    p.add_argument('--no-audio',action='store_true')
    args=p.parse_args()
    size=tuple(map(int,args.size.lower().split('x'))) if args.size else (None,None)
    r=Renderer(args.config,*size)
    if args.qa_dir:
        r.diagnostics(args.qa_dir)
    if args.stills:
        folder=Path(args.qa_dir or Path(args.config).parent/'核对帧');folder.mkdir(parents=True,exist_ok=True)
        for t in map(float,args.stills.split(',')):
            Image.fromarray(r.frame(t)).save(folder/f'output_{t:06.3f}s.png')
    if args.output:
        encode(r,args.output,args.overwrite,not args.no_audio)
    if not any((args.output,args.stills,args.qa_dir)):
        p.error('Choose --output, --stills or --qa-dir')


if __name__=='__main__':
    main()
