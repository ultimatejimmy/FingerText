@echo off
setlocal

:: Locate vswhere (present in VS 2017+)
set VSWHERE="%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist %VSWHERE% (
    echo ERROR: Visual Studio not found. Download the free VS 2022 Build Tools from:
    echo   https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
    echo Install it with the "Desktop development with C++" workload, then re-run this script.
    pause
    exit /b 1
)

:: Find MSBuild from the latest VS install
for /f "usebackq tokens=*" %%i in (`%VSWHERE% -latest -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe`) do set MSBUILD=%%i

if not defined MSBUILD (
    echo ERROR: MSBuild not found in the Visual Studio installation.
    pause
    exit /b 1
)

echo Found MSBuild: %MSBUILD%
echo.

echo Building Win32 Release...
"%MSBUILD%" FingerText2.vcxproj /m /p:Configuration="Unicode Release" /p:Platform=Win32 /p:PlatformToolset=v143 /verbosity:minimal
if %errorlevel% neq 0 ( echo FAILED. & pause & exit /b 1 )
echo Win32 build succeeded: Unicode Release\FingerText2.dll

echo.
echo Building x64 Release...
"%MSBUILD%" FingerText2.vcxproj /m /p:Configuration="Unicode Release" /p:Platform=x64 /p:PlatformToolset=v143 /verbosity:minimal
if %errorlevel% neq 0 ( echo FAILED. & pause & exit /b 1 )
echo x64 build succeeded: x64\Unicode Release\FingerText2.dll

echo.
echo Both builds complete.
pause
