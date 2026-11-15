# 配置与命令

配置文件中的路径都相对该 JSON 所在目录解析。坐标相对各自未经裁切的源图，输出尺寸可按比例改变。只接受与源图长宽比接近的画幅；换画幅先裁切源图并重做蒙版。所有时间均为输出时间轴的绝对秒数。

最小示例（`building.png` 为 900×1600 的源图；坐标须替换为实际标定值）：

```json
{
  "version": 1,
  "time_domain": "output_seconds",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "duration": 2,
  "label": "城市概念画面",
  "scenes": [{
    "id": "windows",
    "source": "building.png",
    "start": 0,
    "end": 2,
    "dark_gain": 0.16,
    "dark_saturation": 0.02,
    "masks": [
      {"id": "a", "polygon": [[100,200],[200,200],[200,350],[100,350]], "feather_px": 0.6},
      {"id": "b", "polygon": [[300,200],[400,200],[400,350],[300,350]], "feather_px": 0.6}
    ],
    "events": [
      {"masks": ["a"], "on": 0.2, "attack": 0.025},
      {"masks": ["b"], "on": 0.5, "attack": 0.025}
    ],
    "full_reveal": {"on": 1.5, "attack": 0.06}
  }]
}
```

`masks` 内还支持：

- `alpha_file`：灰度 PNG 路径，取代 `polygon`，必须与源图同宽同高；0 隐藏，255 显示。
- `holes`：若干内孔多边形，从外 `polygon` 内减去，适合空心框。先相减再羽化。
- `feather_px`：以源图像素为单位的羽化标准差；缩放输出时同步缩放。

`events` 内可设 `off`、`release`、`strength`。`strength` 用于 0–1 的局部亮层混合；多个事件取最大 alpha，不相加曝光。每段镜头必须首尾连续、无重叠、无空洞。最后一镜的 `end` 要等于输出时长。

可选顶层 `audio` 指向音频或带音轨的视频；`audio_start` 为取音起点。没有 `audio` 就输出无声视频。音轨连续保留，首尾做短淡化。

```bash
python3 /path/to/urban-rhythm-mask/scripts/render_rhythm_masks.py \
  --config /path/to/project/timeline.json \
  --size 720x1280 --qa-dir /path/to/project/check \
  --stills 0,0.4,0.8,1.7

python3 /path/to/urban-rhythm-mask/scripts/render_rhythm_masks.py \
  --config /path/to/project/timeline.json \
  --output /path/to/project/result.mp4
```

`--qa-dir` 导出每个对象的全尺寸灰度蒙版及标定图；`--stills` 导出未压缩的时间轴帧。`--no-audio` 可导出无声版本；已存在文件默认不覆盖，明确要重写时加 `--overwrite`。编码先写 `.rendering.mp4`，文件检查通过再改为目标文件名，旁边生成含源图 SHA-256 的 JSON 记录。
