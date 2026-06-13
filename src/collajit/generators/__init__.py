"""The three art modes. Each turns a source-image library into composition output:

* :mod:`~collajit.generators.mosaic` — rebuild a target image from matching tiles,
* :mod:`~collajit.generators.generative` — arrange images by colour / similarity,
* :mod:`~collajit.generators.freeform` — scatter images into editable layers.

Mosaic and generative return a single composite :class:`PIL.Image.Image`; freeform
returns a list of :class:`~collajit.model.layer.Layer` so the pieces stay editable.
"""
