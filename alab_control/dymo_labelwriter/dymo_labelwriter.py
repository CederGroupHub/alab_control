from __future__ import annotations

import subprocess
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
    FONTSIZE = 24
    FONT_FILE = Path(__file__).parent / "Arial.ttf"

    def __init__(self, printer_name: str, sumatra_pdf_path: str | Path = None):
        self.sumatra_pdf_path = Path(sumatra_pdf_path)
        self.printer_name = printer_name

    def get_qr_img(self, qr_code_text: str):
        """Returns a PIL image of a QR code with the given sample string."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=7,
            border=0,
        )
        qr.add_data(qr_code_text)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="transparent").get_image()

    def get_text_img(self, text, box_dim):
        """Get a PIL Image object of a box with centered text."""
        text = "\n".join(t for t in text.splitlines() if t)
        if len(text.splitlines()) > 1:
            raise ValueError("Text must be one line.")
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
            left_text (str): The text to display to the left of the QR code.
            right_text (str): The text to display to the right of the QR code.

        Returns:
            Image: The generated image.
        """
        # Create a new image with a white background
        img = Image.new(
            "RGBA",
            (int(self.LABEL_WIDTH * 300), int(self.LABEL_HEIGHT * 300)),
            "white",
        )

        qr = self.get_qr_img(qr_code_text)
        qr = qr.resize(
            (int(self.LABEL_WIDTH * 0.7 * 300), int(self.LABEL_HEIGHT * 0.7 * 300)),
        )

        # Paste the QR code onto the center of the new image
        qr_x = (img.width - qr.width) // 2
        qr_y = (img.height - qr.height) // 2
        img.paste(qr, (qr_x, qr_y), qr)

        text_height = (img.height - qr.height) // 2 - 5
        up_low_text_width = img.width
        left_right_text_width = qr.width + 10

        if upper_text:
            text_img = self.get_text_img(upper_text, (up_low_text_width, text_height))
            x = (img.width - up_low_text_width) // 2
            y = qr_y - text_height - 5
            text_img = text_img.rotate(0, expand=True)
            img.paste(text_img, (x, y), text_img)
        if lower_text:
            text_img = self.get_text_img(lower_text, (up_low_text_width, text_height))
            x = (img.width - up_low_text_width) // 2
            y = qr_y + qr.height + 5
            text_img = text_img.rotate(180, expand=True)
            img.paste(text_img, (x, y), text_img)
        if left_text:
            text_img = self.get_text_img(
                left_text, (left_right_text_width, text_height)
            )
            x_center = (img.width - qr.width) // 4
            y_center = img.height // 2
            text_img = text_img.rotate(90, expand=True)
            img.paste(
                text_img,
                (x_center - text_img.width // 2, y_center - text_img.height // 2),
                text_img,
            )
        if right_text:
            text_img = self.get_text_img(
                right_text, (left_right_text_width, text_height)
            )
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
        """Call Sumutra PDF to print the image."""
        if not self.sumatra_pdf_path or not self.sumatra_pdf_path.exists():
            raise FileNotFoundError(f"Sumatra PDF not found at {self.sumatra_pdf_path}")
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            suffix=".pdf",
            delete=False,
            dir=self.sumatra_pdf_path.parent,
        ) as f:
            image.save(f.name, "PDF", dpi=(300, 300))
            f.flush()
            f.seek(0)
            # print the file
            cmd = [
                str(self.sumatra_pdf_path),
                f.name,
                "-print-to",  # print to printer
                self.printer_name,
                # "-silent",  # hide the error windows
                "-print-settings",
                '"fit"',  # scale the image to fit the page
            ]
            subprocess.run(cmd, check=True)
            time.sleep(5)

    def print_label(
        self,
        sample_id: ObjectId,
        sample_name: str,
        consumable_rack_level: int,
        consumable_rack_row: int,
        return_image_no_print: bool = False,
    ):
        """
        Print a label with the sample ID and name.

        Args:
            sample_id (str): The sample ID to print.
            sample_name (str): The sample name to print.
            consumable_rack_level (int): The consumable rack level.
            consumable_rack_row (int): The consumable rack row.
            return_image_no_print (bool): If True, return the image without printing it.
        """
        qr_code_text = str(sample_id)
        if len(sample_name) > 22:
            sample_name = sample_name[:22]
        upper_text = sample_name
        lower_text = sample_name
        left_text = f"Level: {consumable_rack_level}  Row: {consumable_rack_row}"
        # current time
        right_text = time.strftime("%Y/%m/%d %H:%M:%S")

        img = self.generate_image(
            qr_code_text, upper_text, lower_text, left_text, right_text
        )
        if return_image_no_print:
            return img

        self._print_file(img)
        return None
