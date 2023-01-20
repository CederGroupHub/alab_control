from typing import List

import cv2
import numpy as np


class WebCam:
    def __init__(self, name: str, port: int):
        self.port = port
        self.name = name

        self._cap = cv2.VideoCapture(self.port)
        if not self._cap.isOpened():
            raise IOError("Cannot open webcam")

    def take_photo(self) -> np.ndarray:
        """
        Take a photo from the webcam
        """
        ret, frame = self._cap.read()
        if not ret:
            raise IOError("Cannot read image from webcam")
        return frame

    def show_video(self):
        """
        Show the video from the webcam
        """
        while True:
            ret, frame = self._cap.read()
            if not ret:
                raise IOError("Cannot read image from webcam")
            cv2.imshow(self.name, frame)
            if cv2.waitKey(1) == 27:
                break
        cv2.destroyAllWindows()

    @staticmethod
    def crop_image(image: np.ndarray, x, y, width, height) -> np.ndarray:
        """
        Crop the image to the given region

        Args:
            image: the image to crop
            x: the x coordinate of the top left corner
            y: the y coordinate of the top left corner
            width: the width of the region
            height: the height of the region

        Returns:
            the cropped image (np.ndarray)
        """
        if x < 0 or y < 0 or width < 0 or height < 0:
            raise ValueError("Cannot crop image with negative values")
        if x + width > image.shape[1] or y + height > image.shape[0]:
            raise ValueError("Cannot crop image outside of the image")
        return image[y:y + height, x:x + width]

    @staticmethod
    def apply_crops(image: np.ndarray, crops: List[List[int]]) -> List[np.ndarray]:
        """
        Apply the given crops to get certain regions of the image
        """
        return [WebCam.crop_image(image, *crop) for crop in crops]


if __name__ == '__main__':
    cam = WebCam("test", 0)
    cam.show_video()
