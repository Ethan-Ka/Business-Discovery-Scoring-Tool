@echo off
setlocal

echo.
echo ========================================
echo Building Business Discovery & Scoring Tool

echo ========================================

pyinstaller --noconfirm --clean business_finder.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete.
echo Output: dist\Business Discovery ^& Scoring Tool.exe

echo NOTE: This build intentionally does NOT bundle any .gguf model files.
echo Models are downloaded at runtime into data\models.
