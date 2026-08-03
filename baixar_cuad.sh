#!/usr/bin/env bash
# Baixa CUAD da FONTE OFICIAL (Zenodo, do Atticus Project) e do ESPELHO do Kaggle, para comparar.
# Licao da Fase 0 de datasets: espelho do Kaggle costuma ser subconjunto desatualizado.
set -u
mkdir -p "$HOME/dados/cuad" && cd "$HOME/dados/cuad" || exit 9

echo "=== 1. FONTE OFICIAL (Zenodo / Atticus Project) ==="
if [ ! -f CUAD_v1.zip ]; then
  curl -sSL --retry 3 -o CUAD_v1.zip \
    "https://zenodo.org/records/4595826/files/CUAD_v1.zip?download=1" \
    -w "  http=%{http_code}  bytes=%{size_download}  tempo=%{time_total}s\n"
else
  echo "  ja baixado"
fi
ls -la CUAD_v1.zip 2>/dev/null
python3 -c "
import zipfile,sys
try:
    z=zipfile.ZipFile('CUAD_v1.zip')
except Exception as e:
    print('  NAO E ZIP VALIDO:',e); sys.exit()
n=z.namelist()
print(f'  arquivos no zip: {len(n)}')
print(f'  descompactado  : {sum(i.file_size for i in z.infolist())/1e6:.1f} MB')
for p in n[:8]: print('   ',p)
"

echo
echo "=== 2. ESPELHO Kaggle (para comparar) ==="
if [ ! -f kaggle_cuad.zip ]; then
  curl -sSL --retry 2 -o kaggle_cuad.zip \
    "https://www.kaggle.com/api/v1/datasets/download/ashyou09/contract-understanding-atticus-dataset-cuad" \
    -w "  http=%{http_code}  bytes=%{size_download}  tempo=%{time_total}s\n"
else
  echo "  ja baixado"
fi
python3 -c "
import zipfile,sys
try:
    z=zipfile.ZipFile('kaggle_cuad.zip')
except Exception as e:
    print('  NAO E ZIP VALIDO:',e); sys.exit()
n=z.namelist()
print(f'  arquivos no zip: {len(n)}')
print(f'  descompactado  : {sum(i.file_size for i in z.infolist())/1e6:.1f} MB')
"
