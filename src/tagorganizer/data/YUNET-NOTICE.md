# Third-party notice: YuNet face detection model

`face_detection_yunet_2026may.onnx` is the YuNet face detector, shipped so that
`tagorganizer.plugins.builtin.detect_faces` works offline.

- **File:** `face_detection_yunet_2026may.onnx`
- **SHA-256:** `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`
- **Size:** 229738 bytes
- **Source:** https://github.com/opencv/opencv_zoo/raw/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet/face_detection_yunet_2026may.onnx
  (opencv_zoo at commit `48b10fa505aeb51fbd127fc60a5c660040e823b7`, the `HEAD`
  of `main` when it was fetched)
- **Upstream:** YuNet by Shiqi Yu and others, https://github.com/ShiqiYu/libfacedetection.train
  (model source recorded in the opencv_zoo README)
- **Re-export:** the 2026may file is the 2023mar model re-exported with dynamic
  input height and width, as opencv_zoo describes. It is not modified here.
- **License:** MIT. Its opencv_zoo directory is licensed under the MIT License
  below. The MIT License is compatible with the GNU GPL v3 or later that covers
  this project. The MIT terms require this notice to travel with copies.

The text of the license, as published in the opencv_zoo directory at the commit
above:

MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.