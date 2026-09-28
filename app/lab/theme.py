"""Visual system: the validated palette, the little CSS the theme file cannot express, and the sidebar wordmark.

Colour roles: ink for text, secondary ink for captions and axis titles, grid for borders and gridlines, surface for
the page and the charts, primary for actions. Chart series keep fixed slots and are never identified by colour alone
(dashes and markers in `charts`). Status colours are the theme's green, orange, red and blue, always with a word."""
import streamlit as st

INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
PRIMARY, DANGER = "#2a78d6", "#b3261e"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]

_CSS = """<style>
.block-container {padding-top: 4.75rem; padding-bottom: 4rem;}
.lab-eyebrow {font-size: 0.8rem; color: #52514e; margin-bottom: -0.5rem;}
.lab-eyebrow .sep {color: #a3a29d; padding: 0 0.4rem;}
.lab-section {font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: #52514e;
              margin: 0.9rem 0 0.1rem;}
.st-key-context_strip {background: #f6f5f2;}
.st-key-context_strip h3 {font-size: 1.15rem; padding: 0; margin: 0;}
.st-key-sidebar_context {background: #fcfcfb;}
div[class*="st-key-danger"] button {border-color: #b3261e; color: #b3261e;}
div[class*="st-key-danger"] button:hover {background: #fbeaea; border-color: #8f1d17; color: #8f1d17;}
div[class*="st-key-danger"] button[data-testid="stBaseButton-primary"] {background: #b3261e; border-color: #b3261e; color: #ffffff;}
div[class*="st-key-danger"] button[data-testid="stBaseButton-primary"]:hover {background: #8f1d17; border-color: #8f1d17; color: #ffffff;}
[data-testid="stMetric"] {padding: 0.65rem 0.9rem;}
[data-testid="stMetricLabel"] {white-space: normal;}
[data-testid="stMetricLabel"] p {font-size: 0.8rem; color: #52514e; white-space: normal; line-height: 1.25;}
[data-testid="stMetricValue"] {font-size: 1.55rem; font-weight: 600; line-height: 1.2;}
[data-testid="stMetricDelta"] {font-size: 0.8rem; white-space: normal;}
</style>"""

_MARK = ('<g fill="none" stroke="#2a78d6" stroke-width="2"><circle cx="9" cy="18" r="4.5" fill="#2a78d6"/>'
         '<circle cx="26" cy="8" r="4.5" fill="#fcfcfb"/><circle cx="26" cy="28" r="4.5" fill="#fcfcfb"/>'
         '<path d="M13 16l9-6M13 20l9 6M26 12.5v11"/></g>')
WORDMARK = ('<svg xmlns="http://www.w3.org/2000/svg" width="232" height="36" viewBox="0 0 232 36">' + _MARK +
            '<text x="40" y="23.5" font-family="system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif" '
            'font-size="16" font-weight="600" fill="#0b0b0b">Social LLM-MAS Lab</text></svg>')
ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36">' + _MARK + '</svg>'


def inject():
    """Page-level CSS and the wordmark at the top of the sidebar. Called once per run by the entry script."""
    st.markdown(_CSS, unsafe_allow_html=True)
    st.logo(WORDMARK, size="large", icon_image=ICON)
