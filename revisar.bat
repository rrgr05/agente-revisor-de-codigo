@echo off
rem Lanza el Agente revisor de codigo con el entorno .venv (sin activarlo).
rem Uso: revisar.bat "D:\proyectos\mi-web" [opciones]
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Falta el entorno .venv. Mira la seccion Instalacion del README.md
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" "%~dp0revisar.py" %*
