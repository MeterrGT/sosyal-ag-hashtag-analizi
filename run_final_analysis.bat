@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo Sosyal Ag Analizi - Final is akisi
echo ============================================
python -c "import sys; print('Python:', sys.version.split()[0]); sys.exit(1 if sys.version_info >= (3,14) else 0)"
if errorlevel 1 (
  echo Bu paket Leiden/igraph icin Python 3.13 ortaminda calistirilmalidir.
  echo Anaconda Prompt'ta: conda activate hashtag-final
  pause
  exit /b 1
)
echo Gerekli paketler yukleniyor...
python -m pip install -r requirements-final.txt
if errorlevel 1 (
  echo Paket kurulumunda hata oldu. Hata mesajini kontrol et.
  pause
  exit /b 1
)
python -c "import igraph, leidenalg, powerlaw; print('Leiden ve powerlaw hazir')"
if errorlevel 1 (
  echo Leiden veya powerlaw yuklenemedi. Python 3.13 ortaminda paket kurulumunu kontrol et.
  pause
  exit /b 1
)
echo Tam analiz basliyor: 100 null model ve 10 tohum.
python finalize_project.py --null-models 100 --seeds 10
if errorlevel 1 (
  echo Analiz tamamlanamadi. Hata mesajini kontrol et.
  pause
  exit /b 1
)
echo Tamamlandi. outputs ve deliverables klasorlerini kontrol et.
pause
