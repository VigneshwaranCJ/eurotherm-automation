"""Compatibility exports; implementations live in focused packages."""
from .reports.settings import set_custom_check, configure_print
from .reports.validation import verify_boundaries, verify_text
from .reports.preview import validate_preview
from .reports.pdf import download_pdf
