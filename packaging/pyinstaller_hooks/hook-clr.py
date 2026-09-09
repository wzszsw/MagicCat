"""Collect the Python.NET assembly needed by the Windows .NET Framework host."""

from pathlib import Path

from PyInstaller.utils.hooks import get_module_file_attribute

_pythonnet = Path(get_module_file_attribute("pythonnet")).parent
datas = [(str(_pythonnet / "runtime" / "Python.Runtime.dll"), "pythonnet/runtime")]
