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
    ignore_rules.append("Исходники.txt")
    ignore_rules.append("download.py")
    ignore_rules.append("favicon.ico")
    ignore_rules.append("LICENSE.txt")
    ignore_rules.append("images/*")
    ignore_rules.append("thumbnails/*")
    ignore_rules.append("postgres_data/*")
    ignore_rules.append("logs/*")
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


def process_single_item(item_path, report_file, ignore_rules, base_path=None):
    """Обрабатывает один элемент (файл или папку) и добавляет его в отчёт."""
    if base_path is None:
        base_path = os.path.dirname(item_path) if os.path.isfile(item_path) else item_path

    if os.path.isdir(item_path):
        # Обрабатываем папку
        report_file.write(f"Дерево каталога: {item_path}\n\n")
        list_directory_tree(item_path, report_file, ignore_rules)

        # Собираем все файлы рекурсивно
        file_paths = []
        for root, dirs, files in os.walk(item_path):
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
                rel_path = os.path.relpath(full_path, base_path)

                # Пропускаем файлы, соответствующие правилам .gitignore
                if is_ignored(rel_path, ignore_rules):
                    continue

                file_paths.append((rel_path, full_path))

        return file_paths

    else:
        # Обрабатываем файл
        rel_path = os.path.relpath(item_path, base_path)
        return [(rel_path, item_path)]


def create_directory_tree_report(output_file, paths):
    """Создаёт полный отчёт с деревом каталогов и содержимым всех файлов."""
    if not paths:
        paths = [os.getcwd()]

    # Определяем базовый путь для относительных путей
    if len(paths) == 1:
        base_path = paths[0] if os.path.isdir(paths[0]) else os.path.dirname(paths[0])
    else:
        # Для нескольких путей используем общий родительский каталог
        common_dir = os.path.commonpath([os.path.abspath(p) for p in paths])
        base_path = common_dir

    ignore_rules = load_gitignore_rules(base_path)

    with open(output_file, 'w', encoding='utf-8') as report_file:
        all_file_paths = []

        # Обрабатываем каждый указанный путь
        for i, path in enumerate(paths):
            if not os.path.exists(path):
                print(f"Предупреждение: путь '{path}' не существует, пропускаем")
                continue

            # Добавляем разделитель между разными путями (кроме первого)
            if i > 0:
                report_file.write("\n" + "=" * 80 + "\n\n")

            file_paths = process_single_item(path, report_file, ignore_rules, base_path)
            all_file_paths.extend(file_paths)

        # Добавляем содержимое файлов
        if all_file_paths:
            report_file.write("\n\nСОДЕРЖИМОЕ ФАЙЛОВ:\n")
            for rel_path, absolute_path in all_file_paths:
                report_file.write(
                    f"\n##################################### {rel_path} #####################################\n")
                report_file.write(get_file_content(absolute_path) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Создание отчёта о содержимом каталога.")
    parser.add_argument('paths', nargs='*', default=[os.getcwd()],
                        help="Файлы и папки для включения в отчёт (по умолчанию текущий каталог).")
    args = parser.parse_args()

    create_directory_tree_report(output_file_name, args.paths)
    print(f"Полный отчёт сохранён в файл: {output_file_name}")
