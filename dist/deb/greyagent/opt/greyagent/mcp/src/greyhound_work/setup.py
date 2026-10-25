from setuptools import setup
from Cython.Build import cythonize
import glob
mods = [f for f in glob.glob("*.py") if f != "setup.py"]
setup(ext_modules=cythonize(mods, compiler_directives={"language_level": "3", "annotation_typing": False}), zip_safe=False)
