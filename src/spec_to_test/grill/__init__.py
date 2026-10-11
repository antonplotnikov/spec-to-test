"""Grill Mode: an interactive QA interviewer and reviewer.

The package holds pure domain logic (no Streamlit, no network), so every
workflow can be tested on its own. The Streamlit page only renders a
`GrillSession` and calls `GrillWorkflow` methods.
"""
