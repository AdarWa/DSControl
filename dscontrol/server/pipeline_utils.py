import cv2
import numpy as np
import easyocr

_reader = easyocr.Reader(['en'])

def crop(image, x, y, w, h):
    """
    Crop an OpenCV image.

    Args:
        image (np.ndarray): Source image.
        x, y, w, h (int): Crop coordinates.

    Returns:
        np.ndarray: Cropped image.
    """
    return image[y:y+h, x:x+w]


def to_grayscale(image):
    """
    Convert an image to grayscale.

    Args:
        image (np.ndarray): Input BGR image.

    Returns:
        np.ndarray: Grayscale image.
    """
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def get_darkest_blob(image, min_area=50):
    """
    Find the darkest contiguous blob of pixels in a grayscale or color image.

    Args:
        image (np.ndarray): Input image (BGR or grayscale).
        min_area (int): Minimum blob area to consider.

    Returns:
        tuple: (x, y, w, h) bounding box of the darkest blob, or None if not found.
    """
    gray = to_grayscale(image) if len(image.shape) == 3 else image

    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    darkest_blob = None
    min_intensity = 255

    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        mask = np.zeros_like(gray)
        cv2.drawContours(mask, [c], -1, 255, -1)
        mean_intensity = cv2.mean(gray, mask=mask)[0]
        if mean_intensity < min_intensity:
            min_intensity = mean_intensity
            x, y, w, h = cv2.boundingRect(c)
            darkest_blob = (x, y, w, h)

    return darkest_blob


def get_darkest_blob_center(image, min_area=50):
    """
    Find the center of the darkest blob in an image.

    Args:
        image (np.ndarray): Input image (BGR or grayscale).
        min_area (int): Minimum blob area to consider.

    Returns:
        tuple: (cx, cy) center of the darkest blob, or None if not found.
    """
    region = get_darkest_blob(image, min_area)
    if region is None:
        return None

    x, y, w, h = region
    cx = int(x + w / 2)
    cy = int(y + h / 2)
    return (cx, cy)


def extract_text(image, crop_region=None, preprocess=True):
    """
    Extract text from an OpenCV image using EasyOCR.

    Args:
        image (np.ndarray): OpenCV image (BGR).
        crop_region (tuple): (x, y, w, h) crop coordinates. Optional.
        preprocess (bool): Whether to apply preprocessing.

    Returns:
        str: Extracted text as a single string.
    """
    if crop_region:
        x, y, w, h = crop_region
        image = crop(image, x, y, w, h)

    gray = to_grayscale(image)

    if preprocess:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 2
        )

    results = _reader.readtext(gray)
    return " ".join([text for (_, text, _) in results]).strip()
