"""Interface of the Social LLM-MAS Lab, split by concern: `auth` (sign-in gate), `state` (labels, cached stores, the
session's open experiment), `theme` (palette, CSS, wordmark), `ui` (page header, cards, context strip, tiles, tables,
dialogs), `charts` (Plotly figures), `results` (results screens), `nav` (pages) and one module per page in `views`.

Streamlit adds the entry script's directory to `sys.path`, so `app/streamlit_app.py` imports this package as `lab`."""
