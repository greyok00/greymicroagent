from setuptools import setup
from Cython.Build import cythonize
setup(ext_modules=cythonize([r'/home/grey/greyagent/mcp/src/research/keys.py', r'/home/grey/greyagent/mcp/src/research/page_builder.py', r'/home/grey/greyagent/mcp/src/research/pipeline.py', r'/home/grey/greyagent/mcp/src/research/research.py'], compiler_directives={'language_level': '3', 'annotation_typing': False}), zip_safe=False)
