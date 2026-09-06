"""Untrusted document validation in a disposable, time-limited child process.

No app configuration or secrets are loaded here. Not an antivirus engine.
"""

import io
import sys
import warnings

MAX_INPUT = 10 * 1024 * 1024
MAX_PIXELS = 12_000_000


def validate(data, kind):
    if kind == "pdf":
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise ValueError("Not PDF")
        from pypdf import PdfReader
        from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
            raise ValueError("Encrypted or too many pages")
        forbidden = {
            "/JavaScript",
            "/JS",
            "/OpenAction",
            "/AA",
            "/Launch",
            "/EmbeddedFiles",
            "/RichMedia",
            "/XFA",
            "/AcroForm",
            "/EF",
        }
        pending = [reader.trailer]
        seen = set()
        count = 0
        while pending:
            item = pending.pop()
            if isinstance(item, IndirectObject):
                key = (item.idnum, item.generation)
                if key in seen:
                    continue
                seen.add(key)
                item = item.get_object()
            count += 1
            if count > 20000:
                raise ValueError("Too complex")
            if isinstance(item, DictionaryObject):
                if str(item.get("/S", "")) in {
                    "/JavaScript",
                    "/Launch",
                    "/SubmitForm",
                    "/ImportData",
                    "/GoToR",
                    "/GoToE",
                    "/Rendition",
                    "/Sound",
                    "/Movie",
                    "/RichMediaExecute",
                }:
                    raise ValueError("Active action")
                if forbidden.intersection(item.keys()):
                    raise ValueError("Active/embedded content")
                pending.extend(item.values())
            elif isinstance(item, ArrayObject):
                pending.extend(item)
        return data
    if kind == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Not PNG")
    if kind in {"jpg", "jpeg"} and not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("Not JPEG")
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}[kind]:
            raise ValueError("Format mismatch")
        if (
            image.width * image.height > MAX_PIXELS
            or getattr(image, "n_frames", 1) != 1
        ):
            raise ValueError("Too large or animated")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        result = io.BytesIO()
        image = ImageOps.exif_transpose(image)
        if image.mode == "RGBA" or "transparency" in image.info:
            rgba = image.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = image.convert("RGB")
        image.info.clear()
        image.save(
            result,
            format="PNG" if kind == "png" else "JPEG",
            quality=95,
            exif=b"",
            icc_profile=None,
        )
        return result.getvalue()


def main():
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if not data or len(data) > MAX_INPUT:
        raise ValueError("Size")
    result = validate(data, sys.argv[1])
    if len(result) > MAX_INPUT:
        raise ValueError("Output size")
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(2)
