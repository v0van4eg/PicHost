#!/usr/bin/env python3
import os
import fnmatch
import argparse

# Указываем имя выходного файла
output_file_name = "Исходники.txt"


def get_file_content(file_path):
    """Получает содержимое файла с обработкой ошибок."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        return f"Ошибка при чтении файла: {str(e)}"


def load_gitignore_rules(startpath):
    """Загружает правила из .gitignore."""
    gitignore_path = os.path.join(startpath, '.gitignore')
    ignore_rules = []
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):  # Игнорируем пустые строки и комментарии
                    ignore_rules.append(line)
    # Добавляем правила для игнорирования
    ignore_rules.append("__pycache__")
    ignore_rules.append("create_src.py")
    ignore_rules.append("text.txt")
    ignore_rules.append("Исходники.txt")
    ignore_rules.append("Readme.md")
    ignore_rules.append("favicon.ico")
    # ignore_rules.append("thumbnails/*")
    ignore_rules.append("LICENSE.txt")
    return ignore_rules


def is_ignored(path, ignore_rules):
    """Проверяет, соответствует ли путь правилам .gitignore."""
    for rule in ignore_rules:
        if fnmatch.fnmatch(path, rule):
            return True
        if fnmatch.fnmatch(os.path.basename(path), rule):
            return True
    return False


def list_directory_tree(startpath, report_file, ignore_rules, prefix=''):
    """Рекурсивно строит дерево каталогов, исключая скрытые элементы и файлы из .gitignore."""
    items = sorted([item for item in os.listdir(startpath) if not item.startswith('.')])

    for index, item in enumerate(items):
        path = os.path.join(startpath, item)
        rel_path = os.path.relpath(path, startpath)

        # Пропускаем файлы и папки, соответствующие правилам .gitignore
        if is_ignored(rel_path, ignore_rules):
            continue

        is_last = index == len(items) - 1
        connector = '└── ' if is_last else '├── '

        report_file.write(f"{prefix}{connector}{item}\n")

        if os.path.isdir(path):
            extension = '    ' if is_last else '│   '
            list_directory_tree(path, report_file, ignore_rules, prefix + extension)


def create_directory_tree_report(output_file, startpath):
    """Создаёт полный отчёт с деревом каталогов и содержимым всех файлов."""
    ignore_rules = load_gitignore_rules(startpath)

    with open(output_file, 'w', encoding='utf-8') as report_file:
        # Записываем дерево каталогов
        report_file.write(f"Дерево каталога: {startpath}\n\n")
        list_directory_tree(startpath, report_file, ignore_rules)

        # Собираем все файлы рекурсивно
        file_paths = []
        for root, dirs, files in os.walk(startpath):
            # Фильтруем скрытые элементы и сортируем
            dirs[:] = sorted([d for d in dirs if not d.startswith('.')])
            files = sorted([f for f in files if not f.startswith('.')])

            # Удаляем __pycache__ из списка директорий
            if '__pycache__' in dirs:
                dirs.remove('__pycache__')
            if 'create_src.py' in dirs:
                dirs.remove('create_src.py')

            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, startpath)

                # Пропускаем файлы, соответствующие правилам .gitignore
                if is_ignored(rel_path, ignore_rules):
                    continue

                file_paths.append(rel_path)

        # Добавляем содержимое файлов
        report_file.write("\n\nСОДЕРЖИМОЕ ФАЙЛОВ:\n")
        for rel_path in file_paths:
            absolute_path = os.path.join(startpath, rel_path)
            report_file.write(f"\n##################################### {rel_path} #####################################\n")
            report_file.write(get_file_content(absolute_path) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Создание отчёта о содержимом каталога.")
    parser.add_argument('directory', nargs='?', default=os.getcwd(), help="Каталог для создания отчёта (по умолчанию текущий каталог).")
    args = parser.parse_args()

    create_directory_tree_report(output_file_name, args.directory)
    print(f"Полный отчёт сохранён в файл: {output_file_name}")
