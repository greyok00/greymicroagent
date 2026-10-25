from setuptools import setup
from Cython.Build import cythonize
setup(ext_modules=cythonize([r'/home/grey/greyagent/mcp/src/memory/db.py', r'/home/grey/greyagent/mcp/src/memory/manager.py', r'/home/grey/greyagent/mcp/src/memory/memory.py'], compiler_directives={'language_level': '3', 'annotation_typing': False}), zip_safe=False)
