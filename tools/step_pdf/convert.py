"""Local converter invoked with an input STEP and an output PDF path."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject

sys.path.insert(0, os.environ.get("FREECAD_LIB", "/usr/lib/freecad-python3/lib"))
import FreeCAD  # noqa: F401, initializes the runtime before importing Part
import Part


class ConversionError(Exception):
    """A failure whose message is safe and useful to show to the person publishing."""


def convert(source, output):
    shape = Part.read(source)
    solids = shape.Solids
    if not solids:
        raise ConversionError("the STEP file contains no solid bodies")
    if len(solids) != 1:
        raise ConversionError(
            f"the STEP file contains {len(solids)} solids and publishing supports exactly one"
        )
    points, triangles = solids[0].tessellate(0.1)
    if not points or not triangles:
        raise ConversionError("the solid produced an empty mesh")
    if max(len(points), len(triangles)) > 1_000_000:
        raise ConversionError("the model is too detailed for the 1,000,000 triangle limit")
    center = solids[0].BoundBox.Center
    rows = [f"{len(points)} {len(triangles)}"]
    rows.extend(f"{p.x - center.x} {p.y - center.y} {p.z - center.z}" for p in points)
    rows.extend(f"{a} {b} {c}" for a, b, c in triangles)
    with TemporaryDirectory() as temp_dir:
        prc = Path(temp_dir) / "model.prc"
        encoder = os.environ.get("STEP_PDF_PRC_ENCODER", "/usr/local/bin/mesh-to-prc")
        subprocess.run([encoder, str(prc)], input="\n".join(rows), text=True, check=True, timeout=30)
        model = DecodedStreamObject()
        model.set_data(prc.read_bytes())

    writer = PdfWriter()
    writer.pdf_header = "%PDF-1.7"
    page = writer.add_blank_page(width=612, height=792)
    title = os.environ.get("STEP_PDF_TITLE", "STEP model")
    writer.add_metadata({"/Title": f"{title} - 3D PDF"})
    writer.root_object[NameObject("/Extensions")] = DictionaryObject({
        NameObject("/ADBE"): DictionaryObject({
            NameObject("/BaseVersion"): NameObject("/1.7"),
            NameObject("/ExtensionLevel"): NumberObject(3),
        }),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    contents = DecodedStreamObject()
    title_hex = title.encode("ascii", "replace").hex()
    contents.set_data((
        f"BT /F1 20 Tf 36 730 Td <{title_hex}> Tj "
        "0 -24 Td /F1 11 Tf "
        "(Open in Acrobat Reader and enable 3D to rotate the model.) Tj ET "
        "0.8 G 36 130 540 532 re S"
    ).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(contents)
    model.update({
        NameObject("/Type"): NameObject("/3D"),
        NameObject("/Subtype"): NameObject("/PRC"),
    })
    # A PDF 3D annotation references an indirect PRC stream.
    writer.add_annotation(page_number=page, annotation=DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/3D"),
        NameObject("/Rect"): ArrayObject([FloatObject(n) for n in (36, 130, 576, 662)]),
        NameObject("/3DD"): writer._add_object(model),
        NameObject("/3DA"): DictionaryObject({
            NameObject("/A"): NameObject("/XA"),
        }),
    }))
    writer.write(output)


if __name__ == "__main__":
    try:
        convert(*sys.argv[1:])
    except ConversionError as error:
        # The app shows the text after this prefix to the person publishing.
        print(f"STEP_PDF_ERROR: {error}", file=sys.stderr)
        sys.exit(2)
