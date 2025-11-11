# simple_download.py
import pandas as pd
import requests
import os


def quick_download(excel_file, output_dir="downloads"):
    """Быстрое скачивание без настроек"""
    df = pd.read_excel(excel_file)
    os.makedirs(output_dir, exist_ok=True)

    # Собираем все URL
    urls = []
    for col in df.columns:
        for cell in df[col].dropna():
            if isinstance(cell, str) and cell.startswith('http'):
                urls.append(cell)

    # Скачиваем
    for url in set(urls):
        try:
            filename = os.path.basename(url)
            response = requests.get(url, timeout=10)
            with open(os.path.join(output_dir, filename), 'wb') as f:
                f.write(response.content)
            print(f"✓ {filename}")
        except:
            print(f"✗ {url}")


# Использование
if __name__ == "__main__":
    quick_download("111.xlsx")
