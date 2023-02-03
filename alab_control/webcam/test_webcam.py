from typing import List
from alab_control.webcam.webcam import WebCam


def get_all_webcams() -> List[WebCam]:
    """
    Get all webcams connected to the computer
    """
    webcams = []
    for i in range(10):
        print(i)
        try:
            webcam = WebCam(f"test_{i}", i)
            webcams.append(webcam)
        except IOError:
            break
    return webcams


if __name__ == '__main__':
    # webcams = get_all_webcams()

    # for webcam in webcams:
    #     print(webcam.name)

    webcam = WebCam("test", 0)
    webcam.show_video()
