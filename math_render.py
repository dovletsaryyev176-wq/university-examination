"""
Utility for rendering text that may contain LaTeX math expressions to PNG images.
Used by PDF generation to display math formulas correctly.
"""
import re
import io

# Matches: $$...$$ | $...$ | \(...\) | \[...\]
_MATH_RE = re.compile(
    r'\$\$[\s\S]+?\$\$'
    r'|\$[^$\n]+?\$'
    r'|\\\([\s\S]+?\\\)'
    r'|\\\[[\s\S]+?\\\]'
)


def has_math(text: str) -> bool:
    if not text:
        return False
    return bool(_MATH_RE.search(text))


def _normalize_delimiters(text: str) -> str:
    r"""Normalize all math delimiters to matplotlib's $...$ format."""
    # Display math: $$...$$ and \[...\] → $...$
    text = re.sub(r'\$\$([\s\S]+?)\$\$', lambda m: '$' + m.group(1).strip() + '$', text)
    text = re.sub(r'\\\[([\s\S]+?)\\\]', lambda m: '$' + m.group(1).strip() + '$', text)
    # Inline math: \(...\) → $...$
    text = re.sub(r'\\\(([\s\S]+?)\\\)', lambda m: '$' + m.group(1).strip() + '$', text)
    return text


def text_to_png(text: str, dpi: int = 200, fontsize: int = 12,
                width_inches: float = 7.5) -> bytes | None:
    """
    Render text (with optional inline LaTeX) to a transparent PNG.
    Returns None if rendering fails or matplotlib is unavailable.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        matplotlib.rcParams.update({
            'mathtext.fontset': 'dejavusans',
            'font.family': 'DejaVu Sans',
            'font.size': fontsize,
        })

        text = _normalize_delimiters(text)

        fig, ax = plt.subplots(1, 1, figsize=(width_inches, 0.65))
        fig.patch.set_facecolor('none')
        ax.set_facecolor('none')
        ax.set_axis_off()
        ax.text(
            0.0, 0.5, text,
            ha='left', va='center',
            fontsize=fontsize,
            transform=ax.transAxes,
            color='black',
        )

        buf = io.BytesIO()
        fig.savefig(
            buf, format='png',
            bbox_inches='tight', dpi=dpi,
            facecolor='none', edgecolor='none',
            pad_inches=0.04,
        )
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception:
        return None
