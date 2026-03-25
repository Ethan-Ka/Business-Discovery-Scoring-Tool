@echo off
REM Business Discovery & Scoring Tool — Auto-Setup Script for Windows
REM This script ensures Python dependencies are installed before running the app.

setlocal enabledelayedexpansion

echo.
echo ========================================
echo Business Discovery Scoring Tool Setup
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org
    echo Make sure "Add Python to PATH" is checked during installation.
    pause
    exit /b 1
)

echo Python found. Installing dependencies...
echo.

REM Install requirements
pip install -q --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo ✓ Dependencies installed successfully.
echo.
echo Starting Business Discovery & Scoring Tool...
echo.

REM Run the app
python sponsor_finder\main.py

pause
