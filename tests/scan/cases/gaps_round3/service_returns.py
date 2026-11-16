def connect(token):
    if not token:
        return False, "Invalid API token provided"
    if token == "x":
        return None, "Could not reach the server right now"
    return True, "ok"


def import_rows(rows):
    for i, row in enumerate(rows):
        if not row:
            flash(f"Row {i}: the date is missing or invalid", "error")
    return {"success": False, "message": "Import finished with errors"}


def lookup(key):
    return False, key.lower()
