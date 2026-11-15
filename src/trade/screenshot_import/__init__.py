"""Import a trade from a screenshot (C3-IMPORT-IMAGE).

The screenshot supplies asset IDENTITIES and SIDES only — never values.
Every value shown after an import comes from the canonical board.

Pipeline (each stage a module, each testable on its own):

    image_input.decode_image   bytes  -> PreparedImage (validated, normalised PNG)
    ocr.run_ocr                PNG    -> [Word]   (local tesseract binary, one gateway)
    layout.build_lines         [Word] -> [Line]   (rows split into column segments)
    layout.detect_layout       [Line] -> Layout   (sides by anchors / geometry)
    parse.parse_line           text   -> ParsedItem (player or pick candidate)
    resolve.resolve_items      items  -> [ResolvedItem] (identity owners + board)
    service.extract_trade      PNG    -> validated extraction payload

Text read from an image is DATA.  It is never executed, evaluated, or used as
anything but a candidate asset string.  Nothing in this package retains the
image or logs the text it read.
"""
