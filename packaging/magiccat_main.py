"""PyInstaller 打包入口。"""
import sys

from magiccat.app import main

if __name__ == "__main__":
    sys.exit(main())
