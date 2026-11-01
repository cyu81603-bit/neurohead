# YuNet face detector

Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet

Model: `face_detection_yunet_2023mar.onnx`.
SHA256: `8F2383E4DD3CFBB4553EA8718107FC0423210DC964F9F4280604804ED2552FA4`.
License: MIT; full notice retained in `yunet_license.txt`.
Download URLs and date are in `yunet_manifest.json`.

The adapter letterboxes each image to 320x320, runs the model at score threshold
0.8 and maps boxes back to original pixels. This is a face detector, not facial
landmark reconstruction or a measured gaze estimator. No robot-training data
or benchmark accuracy is claimed. The project does not redistribute the
user's camera images.
