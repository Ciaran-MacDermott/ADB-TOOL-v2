"""
acc_deck_pkg
============
Core pipeline package for Accuracy Deck Builder (ADB).

This package contains modules for:
- Data loading and transformation (data_io, yoy_transformers)
- Category analysis and ranking (analysis)
- PowerPoint generation (ppt_builder)
- LLM-powered insight generation (llm_insights_free; grammar refine is a no-op shim)
- Prompt management (prompt_loader)
- Slide content management (slide_insight_adder)

Individual modules import their dependencies as needed to optimize startup time.
"""

__version__ = "1.0.0"
__author__ = "Ciaran MacDermott, Circana Data Science"