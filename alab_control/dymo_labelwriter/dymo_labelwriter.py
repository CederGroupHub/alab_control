import tempfile
import time
from pathlib import Path

import qrcode
from bson import ObjectId
from PIL import Image, ImageDraw, ImageFont


class DYMOLabelWriter:
    """
    This is the label printer made by DYMO
    """

    LABEL_WIDTH = 1  # inches
    LABEL_HEIGHT = 1  # inches
    FONTSIZE = 20
    FONT_FILE = Path(__file__).parent / "Arial.ttf"

    def __init__(self, print_name: str):
        self.print_name = print_name

    def get_qr_img(self, qr_code_text: str):
        """Returns a PIL image of a QR code with the given sample string."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=7,
            border=0,
        )
        qr.add_data(qr_code_text)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="transparent").get_image()

    def get_text_img(self, text, box_dim):
        """Get a PIL Image object of a box with centered text."""
        text = "\n".join(t for t in text.splitlines() if t)
        if len(text.splitlines()) > 2:
            raise ValueError("Text must be one or two lines.")
        img = Image.new("RGBA", box_dim)
        font = ImageFont.truetype(str(self.FONT_FILE), self.FONTSIZE)
        draw = ImageDraw.Draw(img)
        draw.text(
            xy=(box_dim[0] // 2 + 2, box_dim[1] // 2 + 2),
            text=text,
            font=font,
            fill="black",
            align="center",
            anchor="mm",
        )
        return img

    def generate_image(
        self,
        qr_code_text: str,
        upper_text: str = "",
        lower_text: str = "",
        left_text: str = "",
        right_text: str = "",
    ) -> Image:
        """
        Generate an image with a QR code and two lines of text.

        Args:
            qr_code_text (str): The text to encode in the QR code.
            upper_text (str): The text to display above the QR code.
            lower_text (str): The text to display below the QR code.

        Returns:
            Image: The generated image.
        """
        qr = self.get_qr_img(qr_code_text)

        qr = qr.resize(
            (int(self.LABEL_WIDTH * 0.6 * 300), int(self.LABEL_HEIGHT * 0.6 * 300)),
        )

        # Create a new image with a white background
        img = Image.new(
            "RGBA",
            (int(self.LABEL_WIDTH * 0.9 * 300), int(self.LABEL_HEIGHT * 0.9 * 300)),
            "white",
        )

        # Paste the QR code onto the center of the new image
        qr_x = (img.width - qr.width) // 2
        qr_y = (img.height - qr.height) // 2
        img.paste(qr, (qr_x, qr_y), qr)

        text_height = (img.height - qr.height) // 2 - 5
        text_width = int(qr.width * 1.2)

        if upper_text:
            text_img = self.get_text_img(upper_text, (text_width, text_height))
            x = (img.width - text_width) // 2
            y = qr_y - text_height - 5
            text_img = text_img.rotate(0, expand=True)
            img.paste(text_img, (x, y), text_img)
        if lower_text:
            text_img = self.get_text_img(lower_text, (text_width, text_height))
            x = (img.width - text_width) // 2
            y = qr_y + qr.height + 5
            text_img = text_img.rotate(180, expand=True)
            img.paste(text_img, (x, y), text_img)
        if left_text:
            text_img = self.get_text_img(left_text, (text_width, text_height))
            x_center = (img.width - qr.width) // 4
            y_center = img.height // 2
            text_img = text_img.rotate(90, expand=True)
            img.paste(
                text_img,
                (x_center - text_img.width // 2, y_center - text_img.height // 2),
                text_img,
            )
        if right_text:
            text_img = self.get_text_img(right_text, (text_width, text_height))
            x_center = (img.width - qr.width) // 4 * 3
            y_center = img.height // 2
            text_img = text_img.rotate(270, expand=True)
            img.paste(
                text_img,
                (
                    x_center + qr.width - text_img.width // 2,
                    y_center - text_img.height // 2,
                ),
                text_img,
            )

        return img

    def _print_file(self, image: Image):
        """Call Windows API to print a file."""
        try:
            import win32api
        except ImportError:
            raise ImportError(
                f"win32api is not installed! Printing with {self.print_name} is only available on Windows."
            )

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            # save the image to a temporary file
            filename = f.name
            image.save(filename, "PDF", resolution=100.0)
            win32api.ShellExecute(0, "print", filename, f'"{self.print_name}"', ".", 0)
            time.sleep(10)  # TODO: find a better way to wait for print job to finish

    def print_label(
        self,
        sample_id: ObjectId,
        sample_name: str,
        consumable_rack_level: int,
        consumable_rack_row: int,
        experiment_name: str,
        return_image_no_print: bool = False,
    ):
        """
        Print a label with the sample ID and name.

        Args:
            sample_id (str): The sample ID to print.
            sample_name (str): The sample name to print.
            consumable_rack_level (int): The consumable rack level.
            consumable_rack_row (int): The consumable rack row.
            experiment_name (str): The experiment name.
            return_image_no_print (bool): If True, return the image without printing it.
        """
        qr_code_text = str(sample_id)
        upper_text = sample_name
        lower_text = sample_name
        left_text = f"Level: {consumable_rack_level}\nRow: {consumable_rack_row}"
        right_text = experiment_name

        img = self.generate_image(
            qr_code_text, upper_text, lower_text, left_text, right_text
        )
        if return_image_no_print:
            return img

        self._print_file(img)
        return None
