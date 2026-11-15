#!/usr/bin/env python3
"""Create an original, deterministic window-grid fixture and its mask timeline."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageDraw


def create(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(720,1280));draw=ImageDraw.Draw(image)
    for y in range(1280):
        f=y/1280
        draw.line((0,y,719,y),fill=(int(13+22*f),int(25+22*f),int(54+23*f)))
    draw.rectangle((60,210,660,1150),fill=(153,137,113))
    draw.rectangle((45,190,675,218),fill=(194,174,138))
    draw.rectangle((45,1149,675,1168),fill=(194,174,138))
    masks=[]
    for row in range(6):
        for col in range(5):
            x=94+col*110;y=275+row*137
            draw.rectangle((x-5,y-5,x+82,y+102),fill=(48,43,40))
            draw.rectangle((x,y,x+77,y+97),fill=(240,177+row*6,84+col*8))
            draw.line((x+38,y,x+38,y+97),fill=(87,65,48),width=4)
            draw.line((x,y+48,x+77,y+48),fill=(87,65,48),width=4)
            masks.append(dict(id=f'w{row+1}{col+1}',polygon=[[x,y],[x+77,y],[x+77,y+97],[x,y+97]],feather_px=.5))
    image_path=folder/'building.png'
    if image_path.exists() or (folder/'timeline.json').exists():
        raise FileExistsError('Choose a new demo folder; existing fixture files are preserved')
    image.save(image_path)
    events=[]
    for row in range(6):
        events.append(dict(masks=[f'w{row+1}3'],on=.2+row*.16,off=1.25,attack=.025))
    events.append(dict(masks=[f'w1{col+1}' for col in range(5)],on=1.25,off=1.6,attack=.025))
    events.append(dict(masks=[f'w6{col+1}' for col in range(5)],on=1.6,off=1.95,attack=.025))
    cfg=dict(version=1,time_domain='output_seconds',width=720,height=1280,fps=30,duration=3,label='',
             scenes=[dict(id='building',source='building.png',start=0,end=3,dark_gain=.18,dark_saturation=.02,
                          masks=masks,events=events,full_reveal=dict(on=2.1,attack=.08))])
    target=folder/'timeline.json';target.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    print(target)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    create(parser.parse_args().output_dir)
