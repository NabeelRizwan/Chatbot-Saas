# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
from PIL import Image

def concat_img(img1, img2):
    from rag.utils.lazy_image import LazyImage, ensure_pil_image

    # Same image must not stack with itself (the LazyImage branch would otherwise
    # concatenate its blob list); mirrors the PIL branch's same-reference guard.
    if img1 is img2:
        return img1

    if (img1 is None or isinstance(img1, LazyImage)) and (img2 is None or isinstance(img2, LazyImage)):
        if img1 and not img2:
            return img1
        if not img1 and img2:
            return img2
        if not img1 and not img2:
            return None
        return LazyImage.merge(img1, img2)

    img1 = ensure_pil_image(img1) or img1
    img2 = ensure_pil_image(img2) or img2
    if img1 and not img2:
        return img1
    if not img1 and img2:
        return img2
    if not img1 and not img2:
        return None

    if img1 is img2:
        return img1

    if isinstance(img1, Image.Image) and isinstance(img2, Image.Image):
        pixel_data1 = img1.tobytes()
        pixel_data2 = img2.tobytes()
        if pixel_data1 == pixel_data2:
            return img1

    width1, height1 = img1.size
    width2, height2 = img2.size

    new_width = max(width1, width2)
    new_height = height1 + height2
    new_image = Image.new("RGB", (new_width, new_height))

    new_image.paste(img1, (0, 0))
    new_image.paste(img2, (0, height1))
    return new_image
