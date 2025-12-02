// static/index.js

// --- Инициализация глобальных переменных ---
console.log('PicHost initialized');

// --- Настройки времени жизни сессии ---
const SESSION_CHECK_INTERVAL = 60000; // Проверка каждую минуту
let sessionCheckTimer = null;

// Функция проверки сессии на сервере
async function checkSession() {
    try {
        const response = await fetch('/api/session-check', {
            method: 'GET',
            credentials: 'same-origin'
        });
        
        if (response.status === 401) {
            // Сессия истекла, перенаправляем на страницу авторизации
            console.log('Session expired, redirecting to login...');
            window.location.href = '/hello';
            return false;
        }
        
        return response.ok;
    } catch (error) {
        console.error('Error checking session:', error);
        return false;
    }
}

// Инициализация проверки сессии
function initSessionCheck() {
    if (sessionCheckTimer) {
        clearInterval(sessionCheckTimer);
    }
    
    sessionCheckTimer = setInterval(async () => {
        await checkSession();
    }, SESSION_CHECK_INTERVAL);
}

// Обертка для fetch, чтобы автоматически обрабатывать 401 ошибки
async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        credentials: 'same-origin'
    });
    
    if (response.status === 401) {
        // Сессия истекла, перенаправляем на страницу авторизации
        console.log('Session expired during API call, redirecting to login...');
        window.location.href = '/hello';
        return null;
    }
    
    return response;
}

// --- Функция форматирования размера файла ---
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// --- Глобальные переменные ---
let droppedFile = null;
let currentAlbumName = null;
// DOM elements
let dropArea, zipFileInput, browseBtn, uploadBtn, uploadForm, linkList, currentAlbumTitle, progressContainer, progressBar, progressText;
let manageBtn, uploadCard, manageCard, backToUploadBtn;
// Новые элементы для селекторов
let albumSelector, articleSelector;
// Новые элементы для загрузки отдельных изображений
let imageDropArea, imageFileInput, imageBrowseBtn, uploadImageBtn, uploadImageForm, imageProgressContainer, imageProgressBar, imageProgressText;
// Элементы для XLSX
let createXlsxBtn, xlsxModal, xlsxTemplateSelect, separatorSelect, generateXlsxBtn, cancelXlsxBtn;
// Элементы для экспорта CSV
let createCSVBtn;
// Элементы для удаления
let deleteAlbumBtn, deleteArticleBtn;
// Элемент для оверлея загрузки
let loadingOverlay;
// Глобальные переменные для статистики
let statsInterval = null;

// Переменная для хранения информации о правах пользователя
let userPermissions = {
    canUpload: false,
    canManageAlbums: false,
    canManageArticles: false,
    canExport: false,
    canViewFiles: false,
    canViewStats: false,
    canUploadIndividual: false
};

// Конфигурация превью
const PREVIEW_CONFIG = {
    thumbnail: {
        width: 120,
        height: 120,
        quality: 60
    },
    preview: {
        width: 400,
        height: 400,
        quality: 80
    }
};

// --- Конец глобальных переменных ---

// --- Вспомогательная функция ---
const Path = {
    basename: (path) => {
        const parts = path.split(/[\\/]/);
        return parts[parts.length - 1] || path;
    }
};

// Функция для форматирования размера в читаемый вид
function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Функция обновления прогресс-бара диска
function updateDiskBar(percentUsed) {
    const diskBarFill = document.getElementById('diskBarFill');
    if (diskBarFill) {
        diskBarFill.style.width = `${percentUsed}%`;
        diskBarFill.setAttribute('data-percent', `${percentUsed}%`);

        // Меняем цвет в зависимости от заполненности
        if (percentUsed > 90) {
            diskBarFill.style.background = '#e74c3c';
        } else if (percentUsed > 70) {
            diskBarFill.style.background = '#f39c12';
        } else {
            diskBarFill.style.background = '#2ecc71';
        }
    }
}

// Функция загрузки статистики
async function loadStats() {
    // Если пользователь не имеет прав на просмотр статистики, не загружаем
    if (!userPermissions.canViewStats) {
        return null;
    }

    try {
        const response = await apiFetch('/api/stats');
        if (!response) return null; // Проверка на null в случае 401
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('📊 Stats data received:', data);

        if (data.error) {
            throw new Error(data.error);
        }

        updateStatsDisplay(data);
        return data;
    } catch (error) {
        console.error('❌ Error loading stats:', error);
        updateStatsDisplay(null, error.message);
        return null;
    }
}

// Функция обновления отображения статистики
function updateStatsDisplay(statsData, error = null) {
    const diskBarFill = document.getElementById('diskBarFill');
    const diskUsage = document.getElementById('diskUsage');
    const totalFiles = document.getElementById('totalFiles');
    const totalAlbums = document.getElementById('totalAlbums');

    if (!statsData || error || statsData.status === 'error') {
        const errorMessage = error || statsData?.error || 'Ошибка загрузки данных';
        if (diskUsage) diskUsage.textContent = errorMessage;
        if (totalFiles) totalFiles.textContent = '—';
        if (totalAlbums) totalAlbums.textContent = '—';
        if (diskBarFill) diskBarFill.style.width = '0%';
        return;
    }

    const { disk_stats, files } = statsData;

    console.log('📊 Stats data received:', statsData);

    // Получаем первую доступную статистику диска
    let mainStats = null;
    let mountPoint = null;

    // Приоритет точек монтирования
    const mountPriority = ['/app/images', '/images', '/'];

    for (const mp of mountPriority) {
        if (disk_stats && disk_stats[mp]) {
            mainStats = disk_stats[mp];
            mountPoint = mp;
            break;
        }
    }

    // Если не нашли по приоритету, берем первую доступную
    if (!mainStats && disk_stats && Object.keys(disk_stats).length > 0) {
        mountPoint = Object.keys(disk_stats)[0];
        mainStats = disk_stats[mountPoint];
    }

    // Обновляем информацию о дисковом пространстве
    if (mainStats && diskBarFill && diskUsage) {
        const percentUsed = mainStats.percent_used || 0;
        updateDiskBar(percentUsed);

        // Форматируем отображение в GB
        const usedGB = (mainStats.used / 1024 / 1024 / 1024).toFixed(1);
        const totalGB = (mainStats.total / 1024 / 1024 / 1024).toFixed(1);
        const freeGB = (mainStats.free / 1024 / 1024 / 1024).toFixed(1);

        // Обновляем текст под баром
        diskUsage.textContent = `Свободно ${freeGB} GB из ${totalGB} GB`;
        diskUsage.title = `Использовано: ${usedGB} GB (${percentUsed}%)`;

    } else {
        if (diskUsage) diskUsage.textContent = 'Статистика диска недоступна';
        if (diskBarFill) diskBarFill.style.width = '0%';
    }

    // Обновляем информацию о файлах
    if (totalFiles && files) {
        totalFiles.textContent = files.total_files ? files.total_files.toLocaleString() : '0';
    } else if (totalFiles) {
        totalFiles.textContent = '—';
    }

    if (totalAlbums && files) {
        totalAlbums.textContent = files.total_albums ? files.total_albums.toLocaleString() : '0';
    } else if (totalAlbums) {
        totalAlbums.textContent = '—';
    }
}

// Функция инициализации статистики
function initStats() {
    const statsCard = document.getElementById('statsCard');
    const refreshStatsBtn = document.getElementById('refreshStatsBtn');

    if (!statsCard || !refreshStatsBtn) {
        console.warn('Stats elements not found');
        return;
    }

    // Показываем карточку статистики только если есть права
    if (userPermissions.canViewStats) {
        statsCard.style.display = 'block';

        // Загружаем статистику при инициализации
        loadStats();

        // Обработчик для кнопки обновления
        refreshStatsBtn.addEventListener('click', () => {
            refreshStatsBtn.disabled = true;
            refreshStatsBtn.innerHTML = '<span>Загрузка...</span>';

            loadStats().finally(() => {
                setTimeout(() => {
                    refreshStatsBtn.disabled = false;
                    refreshStatsBtn.innerHTML = '<span>🔄 Обновить</span>';
                }, 1000);
            });
        });

        // Автоматическое обновление статистики каждые 5 минут
        statsInterval = setInterval(loadStats, 5 * 60 * 1000);
    } else {
        statsCard.style.display = 'none';
    }
}

// Функция для остановки автоматического обновления
function stopStatsAutoRefresh() {
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
    }
}

// --- Инициализация прав пользователя ---
function initUserPermissions() {
    const body = document.body;

    userPermissions = {
        canUpload: body.getAttribute('data-can-upload') === 'true',
        canManageAlbums: body.getAttribute('data-can-manage-albums') === 'true',
        canManageArticles: body.getAttribute('data-can-manage-articles') === 'true',
        canExport: body.getAttribute('data-can-export') === 'true',
        canViewFiles: body.getAttribute('data-can-view-files') === 'true',
        canViewStats: body.getAttribute('data-can-view-stats') === 'true',
        canUploadIndividual: body.getAttribute('data-can-upload-individual') === 'true'
    };

    console.log('👤 User permissions:', userPermissions);

    // Визуально обновляем интерфейс на основе прав
    updateUIForPermissions();
}

// --- Обновление интерфейса на основе прав ---
function updateUIForPermissions() {
    // Управление кнопкой загрузки
    const uploadBtn = document.getElementById('uploadBtn');
    if (uploadBtn) {
        if (!userPermissions.canUpload) {
            uploadBtn.style.display = 'none';
        }
    }

    // Управление карточкой управления
    const manageBtn = document.getElementById('manageBtn');
    if (manageBtn) {
        // Показываем кнопку управления только если есть хотя бы одно из прав
        const hasAnyManagementPermission = userPermissions.canManageAlbums ||
                                         userPermissions.canManageArticles ||
                                         userPermissions.canExport;
        if (!hasAnyManagementPermission) {
            manageBtn.style.display = 'none';
        }
    }

    // Управление секцией просмотра файлов
    const linksSection = document.querySelector('.links-section');
    if (linksSection && !userPermissions.canViewFiles) {
        linksSection.innerHTML = `
            <h2>❌ Доступ запрещен</h2>
            <div class="empty-state" style="color: #e74c3c;">
                ❌ У вас нет прав для просмотра файлов. Обратитесь к администратору.
            </div>
        `;
    }

    // ОСНОВНОЕ ИЗМЕНЕНИЕ: Если пользователь не может загружать, но может просматривать - показываем управление сразу
    if (!userPermissions.canUpload && userPermissions.canViewFiles) {
        console.log('👀 User is viewer-only, showing management interface immediately');

        // Скрываем карточку загрузки и показываем управление
        if (uploadCard) uploadCard.style.display = 'none';
        if (manageCard) manageCard.style.display = 'flex';
        if (backToUploadBtn) backToUploadBtn.style.display = 'none';
        if (manageBtn) manageBtn.style.display = 'none'; // Скрываем кнопку перехода к управлению

        // Загружаем альбомы сразу
        setTimeout(() => {
            loadAlbums().then(albums => {
                if (albums && albums.length > 0) {
                    // Автоматически выбираем первый альбом и загружаем его файлы
                    albumSelector.value = albums[0];
                    loadArticles(albums[0]).then(() => {
                        showFilesForAlbum(albums[0]);
                    });
                }
            });
        }, 100);
    }
}

// --- Система ленивой загрузки изображений ---
class LazyLoader {
    constructor() {
        this.observer = null;
        this.init();
    }

    init() {
        if ('IntersectionObserver' in window) {
            this.observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        this.loadImage(entry.target);
                        this.observer.unobserve(entry.target);
                    }
                });
            }, {
                rootMargin: '50px 0px',
                threshold: 0.1
            });
        }
    }

    observe(element) {
        if (this.observer) {
            this.observer.observe(element);
        } else {
            // Fallback: загружаем сразу если IntersectionObserver не поддерживается
            this.loadImage(element);
        }
    }

    loadImage(img) {
        const src = img.getAttribute('data-src');
        if (src) {
            img.onload = () => {
                img.classList.add('loaded');
            };
            img.src = src;
            img.removeAttribute('data-src');
        }
    }
}

const lazyLoader = new LazyLoader();

// --- Функция инициализации DOM элементов ---
function initializeElements() {
    dropArea = document.getElementById('dropArea');
    zipFileInput = document.getElementById('zipFile');
    browseBtn = document.getElementById('browseBtn');
    uploadBtn = document.getElementById('uploadBtn');
    uploadForm = document.getElementById('uploadForm');
    linkList = document.getElementById('linkList');
    currentAlbumTitle = document.getElementById('currentAlbumTitle');
    manageBtn = document.getElementById('manageBtn');
    uploadCard = document.getElementById('uploadCard');
    manageCard = document.getElementById('manageCard');
    backToUploadBtn = document.getElementById('backToUploadBtn');
    progressContainer = document.getElementById('progressContainer');
    progressBar = document.getElementById('progressBar');
    progressText = document.getElementById('progressText');
    loadingOverlay = document.getElementById('loadingOverlay');

    // Новые элементы селекторов
    albumSelector = document.getElementById('albumSelector');
    articleSelector = document.getElementById('articleSelector');
    
    // Новые элементы для загрузки отдельных изображений
    imageDropArea = document.getElementById('imageDropArea');
    imageFileInput = document.getElementById('imageFile');
    imageBrowseBtn = document.getElementById('imageBrowseBtn');
    uploadImageBtn = document.getElementById('uploadImageBtn');
    uploadImageForm = document.getElementById('uploadImageForm');
    imageProgressContainer = document.getElementById('imageProgressContainer');
    imageProgressBar = document.getElementById('imageProgressBar');
    imageProgressText = document.getElementById('imageProgressText');

    // Новые элементы для XLSX
    createXlsxBtn = document.getElementById('createXlsxBtn');
    xlsxModal = document.getElementById('xlsxModal');
    xlsxTemplateSelect = document.getElementById('xlsxTemplateSelect');
    separatorSelect = document.getElementById('separatorSelect');
    generateXlsxBtn = document.getElementById('generateXlsxBtn');
    cancelXlsxBtn = document.getElementById('cancelXlsxBtn');

    // Новые элементы для экспорта CSV
    createCSVBtn = document.getElementById('createCSVBtn');

    // Отладочная информация
    console.log('🔍 CSV Button element:', createCSVBtn);
    console.log('🔍 XLSX Button element:', createXlsxBtn);

    // Проверяем только основные элементы
    if (!dropArea || !zipFileInput || !browseBtn || !uploadForm || !linkList || !currentAlbumTitle || !progressContainer || !progressBar || !progressText || !loadingOverlay) {
        console.error('One or more required DOM elements not found!');
        return false;
    }

    // Инициализируем права пользователя
    initUserPermissions();

    // Инициализация статистики
    initStats();

    return true;
}

// --- Функции для управления оверлеем загрузки ---
function showLoadingOverlay(message = 'Обработка архива...', details = 'Распаковываем файлы и создаем превью. Это может занять несколько минут.') {
    if (loadingOverlay) {
        const textElement = loadingOverlay.querySelector('.loading-text');
        const detailsElement = loadingOverlay.querySelector('.loading-details');

        if (textElement) textElement.textContent = message;
        if (detailsElement) detailsElement.textContent = details;

        loadingOverlay.classList.add('show');
    }
}

function hideLoadingOverlay() {
    if (loadingOverlay) {
        loadingOverlay.classList.remove('show');
    }
}

// --- Функция обновления UI ---
function updateUI() {
    if (!zipFileInput || !dropArea || !uploadBtn) {
        console.error('DOM elements not initialized for updateUI');
        return;
    }
    const file = droppedFile || (zipFileInput.files[0] || null);
    if (file) {
        const fileSize = formatFileSize(file.size);
        dropArea.innerHTML = `<p>Выбран файл: <strong>${file.name}</strong></p><p>Размер: ${fileSize}</p><p>Готов к загрузке</p>`;
        if (userPermissions.canUpload) {
            uploadBtn.disabled = false;
        }
    } else {
        dropArea.innerHTML = `<p>Перетащите ZIP-архив сюда</p><p>или</p><button type="button" class="btn" id="browseBtn">Выбрать файл</button>`;
        uploadBtn.disabled = true;
    }
}

// --- Функция копирования в буфер обмена ---
function copyToClipboard(text, button) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(() => {
            console.log('Скопировано через Clipboard API');
            updateButtonState(button);
        }).catch(err => {
            console.error('Ошибка Clipboard API:', err);
            fallbackCopyTextToClipboard(text, button);
        });
    } else {
        console.warn('Clipboard API недоступен, используется резервный метод.');
        fallbackCopyTextToClipboard(text, button);
    }
}

function fallbackCopyTextToClipboard(text, button) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.cssText = `
        position: fixed;
        top: -9999px;
        left: -9999px;
        width: 2em;
        height: 2em;
        z-index: 10000;
        opacity: 0;
        pointer-events: none;
    `;
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        const successful = document.execCommand('copy');
        if (successful) {
            console.log('Скопировано через execCommand');
            updateButtonState(button);
        } else {
            console.error('execCommand copy не удался');
            alert('Не удалось скопировать текст. Пожалуйста, скопируйте вручную.');
        }
    } catch (err) {
        console.error('Exception при выполнении execCommand copy:', err);
        alert('Не удалось скопировать текст. Пожалуйста, скопируйте вручную.');
    }
    document.body.removeChild(textArea);
}

function updateButtonState(button) {
    const originalText = button.textContent;
    button.textContent = 'Скопировано!';
    button.classList.add('copied');
    setTimeout(() => {
        button.textContent = originalText;
        button.classList.remove('copied');
    }, 2000);
}

// --- Функции для подсчета файлов ---
async function getAlbumFileCount(albumName) {
    try {
        const response = await fetch(`/api/count/album/${encodeURIComponent(albumName)}`);
        if (!response.ok) throw new Error('Failed to get album count');
        const data = await response.json();
        return data.count || 0;
    } catch (error) {
        console.error('Error getting album file count:', error);
        return 0;
    }
}

async function getArticleFileCount(albumName, articleName) {
    try {
        const response = await fetch(`/api/count/article/${encodeURIComponent(albumName)}/${encodeURIComponent(articleName)}`);
        if (!response.ok) throw new Error('Failed to get article count');
        const data = await response.json();
        return data.count || 0;
    } catch (error) {
        console.error('Error getting article file count:', error);
        return 0;
    }
}

// Функция для обновления заголовка с количеством файлов
async function updateTitleWithCount(albumName, articleName = '') {
    if (!currentAlbumTitle) return;

    let count = 0;
    let title = '';

    if (albumName && articleName) {
        count = await getArticleFileCount(albumName, articleName);
        title = `Изображения в "${albumName}" (артикул: ${articleName}) - ${count} файлов`;
    } else if (albumName) {
        count = await getAlbumFileCount(albumName);
        title = `Изображения в "${albumName}" - ${count} файлов`;
    } else {
        title = 'Прямые ссылки на изображения';
    }

    currentAlbumTitle.textContent = title;
}

// --- Функции для работы с селекторами ---
async function loadAlbums() {
    try {
        const response = await apiFetch('/api/albums');
        if (!response) return []; // Проверка на null в случае 401
        
        if (!response.ok) throw new Error('Failed to load albums');
        const albums = await response.json();

        albumSelector.innerHTML = '<option value="">-- Выберите альбом --</option>';
        albums.forEach(album => {
            const option = document.createElement('option');
            option.value = album;
            option.textContent = album;
            albumSelector.appendChild(option);
        });

        updateDeleteButtonsState();
        return albums;
    } catch (error) {
        console.error('Error loading albums:', error);
        albumSelector.innerHTML = '<option value="">-- Ошибка загрузки --</option>';
        updateDeleteButtonsState();
        return [];
    }
}

async function loadArticles(albumName) {
    if (!albumName) {
        articleSelector.innerHTML = '<option value="">-- Сначала выберите альбом --</option>';
        articleSelector.disabled = true;
        updateDeleteButtonsState();
        return;
    }

    try {
        console.log('Loading articles for album:', albumName);
        const response = await apiFetch(`/api/articles/${encodeURIComponent(albumName)}`);
        if (!response) return []; // Проверка на null в случае 401
        
        if (!response.ok) throw new Error(`HTTP ${response.status}: Failed to load articles`);

        const articles = await response.json();
        console.log('Received articles:', articles);

        articleSelector.innerHTML = '<option value="">-- Все артикулы --</option>';
        articles.forEach(article => {
            const option = document.createElement('option');
            option.value = article;
            option.textContent = article;
            articleSelector.appendChild(option);
        });

        articleSelector.disabled = false;
        updateDeleteButtonsState();
        return articles;
    } catch (error) {
        console.error('Error loading articles:', error);
        articleSelector.innerHTML = '<option value="">-- Ошибка загрузки --</option>';
        articleSelector.disabled = false;
        updateDeleteButtonsState();
        return [];
    }
}

function clearLinkList() {
    if (linkList) {
        if (!userPermissions.canUpload) {
            linkList.innerHTML = '<div class="empty-state">Выберите альбом для просмотра изображений</div>';
        } else {
            linkList.innerHTML = '<div class="empty-state">Загрузите ZIP-архив, чтобы получить прямые ссылки на изображения</div>';
        }
    }
    if (currentAlbumTitle) {
        currentAlbumTitle.textContent = 'Прямые ссылки на изображения';
    }
}

// --- Создание элемента списка файлов с превью ---
function createFileListItem(item, parentElement) {
    const li = document.createElement('li');
    li.className = 'link-item';

    const fileData = typeof item === 'object' ? item : {
        filename: item[0],
        album_name: item[1],
        article_number: item[2],
        public_link: item[3],
        created_at: item[4],
        thumbnail_url: `/thumbnails/small/${item[0]}`,
        preview_url: `/thumbnails/medium/${item[0]}`,
        file_size: 0
    };

    const previewDiv = document.createElement('div');
    previewDiv.className = 'link-preview';

    const img = document.createElement('img');
    img.className = 'lazy-image';
    img.width = PREVIEW_CONFIG.thumbnail.width;
    img.height = PREVIEW_CONFIG.thumbnail.height;

    img.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjYwIiBoZWlnaHQ9IjYwIiBmaWxsPSIjRjFGNUY5Ii8+CjxwYXRoIGQ9Ik0zNi41IDI0LjVIMjMuNVYzNy41SDM2LjVWMjQuNVoiIGZpbGw9IiNEOEUxRTYiLz4KPHBhdGggZD0iTTI1IDI2SDM1VjI5SDI1VjI2WiIgZmlsbD0iI0Q4RTFFNiIvPgo8cGF0aCBkPSJNMjUgMzFIMzJWMzRIMjVWMzFaIiBmaWxsPSIjRDhFMUU2Ii8+Cjwvc3ZnPg==';
    img.setAttribute('data-src', fileData.thumbnail_url);
    img.alt = Path.basename(fileData.filename);

    img.addEventListener('click', () => showPreviewModal(fileData));

    img.onerror = function() {
        this.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjYwIiBoZWlnaHQ9IjYwIiBmaWxsPSIjRjFGNUY5Ii8+CjxwYXRoIGQ9Ik0zNi41IDI0LjVIMjMuNVYzNy41SDM2LjVWMjQuNVoiIGZpbGw9IiNEOEUxRTYiLz4KPHBhdGggZD0iTTI1IDI2SDM1VjI5SDI1VjI2WiIgZmlsbD0iI0Q4RTFFNiIvPgo8cGF0aCBkPSJNMjUgMzFIMzJWMzRIMjVWMzFaIiBmaWxsPSIjRDhFMUU2Ii8+Cjwvc3ZnPg==';
    };

    const urlDiv = document.createElement('div');
    urlDiv.className = 'link-url';
    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.value = fileData.public_link;
    urlInput.readOnly = true;
    urlInput.className = 'link-url-input';
    urlInput.title = 'Прямая ссылка на изображение';

    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'btn btn-copy copy-btn';
    copyBtn.textContent = 'Копировать';
    copyBtn.addEventListener('click', () => copyToClipboard(fileData.public_link, copyBtn));

    const fileInfo = document.createElement('div');
    fileInfo.className = 'file-info';
    fileInfo.textContent = `${Path.basename(fileData.filename)} • ${formatFileSize(fileData.file_size || 0)}`;

    urlDiv.appendChild(urlInput);
    previewDiv.appendChild(img);
    previewDiv.appendChild(urlDiv);
    previewDiv.appendChild(copyBtn);
    li.appendChild(previewDiv);
    li.appendChild(fileInfo);
    parentElement.appendChild(li);

    lazyLoader.observe(img);
}

// --- Модальное окно для просмотра полноразмерного изображения ---
function showPreviewModal(fileData) {
    let modal = document.getElementById('previewModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'previewModal';
        modal.className = 'preview-modal';
        modal.innerHTML = `
            <div class="modal-content">
                <button class="modal-close">&times;</button>
                <img class="modal-image" src="" alt="">
                <div class="modal-info">
                    <div class="modal-filename"></div>
                    <div class="modal-actions">
                        <button class="btn btn-copy-full">Копировать ссылку</button>
                        <a class="btn btn-view-original" target="_blank">Открыть оригинал</a>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        modal.querySelector('.modal-close').addEventListener('click', () => {
            modal.style.display = 'none';
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.style.display === 'flex') {
                modal.style.display = 'none';
            }
        });
    }

    const modalImage = modal.querySelector('.modal-image');
    const modalFilename = modal.querySelector('.modal-filename');
    const copyFullBtn = modal.querySelector('.btn-copy-full');
    const viewOriginalBtn = modal.querySelector('.btn-view-original');

    modalImage.src = fileData.preview_url;
    modalFilename.textContent = Path.basename(fileData.filename);
    viewOriginalBtn.href = fileData.public_link;

    copyFullBtn.onclick = () => copyToClipboard(fileData.public_link, copyFullBtn);

    modal.style.display = 'flex';
}

// --- Загрузка и отображение файлов для альбома с превью ---
async function showFilesForAlbum(albumName, articleName = '') {
    if (!currentAlbumTitle || !linkList) {
        console.error('DOM elements for file list not initialized');
        return;
    }

    if (!userPermissions.canViewFiles) {
        if (linkList) {
            linkList.innerHTML = '<div class="empty-state" style="color: #e74c3c;">❌ У вас нет прав для просмотра файлов</div>';
        }
        return;
    }

    await updateTitleWithCount(albumName, articleName);

    try {
        let url;
        if (articleName) {
            url = `/api/thumbnails/${encodeURIComponent(albumName)}/${encodeURIComponent(articleName)}`;
        } else {
            url = `/api/thumbnails/${encodeURIComponent(albumName)}`;
        }

        console.log('Fetching URL:', url);

        const response = await apiFetch(url);
        if (!response) return; // Проверка на null в случае 401
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const files = await response.json();
        console.log('Received files:', files);

        if (!files || files.length === 0) {
            linkList.innerHTML = '<div class="empty-state">В выбранной категории нет файлов.</div>';
            return;
        }

        linkList.innerHTML = '';

        if (articleName) {
            const extractSuffix = (filename) => {
                const baseName = Path.basename(filename);
                const match = baseName.match(/_([0-9]+)(\.[^.]*)?$/);
                return match ? parseInt(match[1], 10) : 0;
            };

            files.sort((a, b) => {
                const suffixA = extractSuffix(a.filename);
                const suffixB = extractSuffix(b.filename);
                return suffixA - suffixB;
            });

            files.forEach(item => {
                createFileListItem(item, linkList);
            });
        } else {
            const groupedFiles = {};
            files.forEach(item => {
                const article = item.article_number;
                if (!groupedFiles[article]) {
                    groupedFiles[article] = [];
                }
                groupedFiles[article].push(item);
            });

            const sortedArticles = Object.keys(groupedFiles).sort();

            if (sortedArticles.length === 0) {
                linkList.innerHTML = '<div class="empty-state">В альбоме нет файлов.</div>';
                return;
            }

            sortedArticles.forEach(article => {
                const articleHeader = document.createElement('li');
                articleHeader.className = 'article-header';
                articleHeader.textContent = `Артикул: ${article}`;
                linkList.appendChild(articleHeader);

                const filesForArticle = groupedFiles[article];
                const extractSuffix = (filename) => {
                    const baseName = Path.basename(filename);
                    const match = baseName.match(/_([0-9]+)(\.[^.]*)?$/);
                    return match ? parseInt(match[1], 10) : 0;
                };

                filesForArticle.sort((a, b) => {
                    const suffixA = extractSuffix(a.filename);
                    const suffixB = extractSuffix(b.filename);
                    return suffixA - suffixB;
                });

                filesForArticle.forEach(item => {
                    createFileListItem(item, linkList);
                });
            });
        }
    } catch (error) {
        console.error('Error loading files:', error);
        linkList.innerHTML = `<div class="empty-state">Ошибка загрузки файлов: ${error.message}</div>`;
    }
}

// --- Функции для удаления ---
async function deleteAlbum(albumName) {
    if (!userPermissions.canManageAlbums) {
        alert('❌ У вас нет прав для удаления альбомов');
        return;
    }

    if (!albumName || !confirm(`Вы уверены, что хотите удалить альбом "${albumName}"? Это действие нельзя отменить.`)) {
        return;
    }

    try {
        const response = await apiFetch(`/api/delete-album/${encodeURIComponent(albumName)}`, {
            method: 'DELETE'
        });
        if (!response) return; // Проверка на null в случае 401

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Ошибка при удалении альбома');
        }

        const result = await response.json();

        await loadAlbums();
        clearLinkList();
        updateDeleteButtonsState();

    } catch (error) {
        console.error('Error deleting album:', error);
        alert(`Ошибка удаления альбома: ${error.message}`);
    }
}

async function deleteArticle(albumName, articleName) {
    if (!userPermissions.canManageArticles) {
        alert('❌ У вас нет прав для удаления артикулов');
        return;
    }

    if (!albumName || !articleName || !confirm(`Вы уверены, что хотите удалить артикул "${articleName}" из альбома "${albumName}"? Это действие нельзя отменить.`)) {
        return;
    }

    try {
        const response = await apiFetch(`/api/delete-article/${encodeURIComponent(albumName)}/${encodeURIComponent(articleName)}`, {
            method: 'DELETE'
        });
        if (!response) return; // Проверка на null в случае 401

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Ошибка при удалении артикула');
        }

        const result = await response.json();

        await loadArticles(albumName);
        clearLinkList();
        updateDeleteButtonsState();

        if (articleSelector.value === articleName) {
            articleSelector.value = '';
            showFilesForAlbum(albumName);
        }

    } catch (error) {
        console.error('Error deleting article:', error);
        alert(`Ошибка удаления артикула: ${error.message}`);
    }
}

// --- Обновление состояния кнопок удаления ---
function updateDeleteButtonsState() {
    const selectedAlbum = albumSelector.value;
    const selectedArticle = articleSelector.value;

    if (deleteAlbumBtn) {
        deleteAlbumBtn.disabled = !selectedAlbum;
        deleteAlbumBtn.style.display = selectedAlbum ? 'flex' : 'none';
    }

    if (deleteArticleBtn) {
        deleteArticleBtn.disabled = !selectedAlbum || !selectedArticle;
        deleteArticleBtn.style.display = (selectedAlbum && selectedArticle) ? 'flex' : 'none';
    }
}

// --- Инициализация кнопок удаления ---
function initDeleteButtons() {
    if (!userPermissions.canManageAlbums && !userPermissions.canManageArticles) {
        return; // Не создаем кнопки если нет прав
    }

    let deleteButtonsContainer = document.getElementById('deleteButtonsContainer');
    if (!deleteButtonsContainer) {
        deleteButtonsContainer = document.createElement('div');
        deleteButtonsContainer.id = 'deleteButtonsContainer';
        deleteButtonsContainer.className = 'delete-buttons-container';
        const manageCardContent = document.querySelector('.manage-card-content');
        if (manageCardContent) {
            const selectorGroups = manageCardContent.querySelectorAll('.selector-group');
            const lastSelectorGroup = selectorGroups[selectorGroups.length - 1];
            if (lastSelectorGroup && lastSelectorGroup.nextSibling) {
                manageCardContent.insertBefore(deleteButtonsContainer, lastSelectorGroup.nextSibling);
            } else {
                manageCardContent.appendChild(deleteButtonsContainer);
            }
        }
    }

    if (!deleteAlbumBtn && userPermissions.canManageAlbums) {
        deleteAlbumBtn = document.createElement('button');
        deleteAlbumBtn.id = 'deleteAlbumBtn';
        deleteAlbumBtn.className = 'btn btn-danger';
        deleteAlbumBtn.innerHTML = '🗑️ Удалить альбом';
        deleteAlbumBtn.disabled = true;
        deleteAlbumBtn.addEventListener('click', () => {
            deleteAlbum(albumSelector.value);
        });
        deleteButtonsContainer.appendChild(deleteAlbumBtn);
    }

    if (!deleteArticleBtn && userPermissions.canManageArticles) {
        deleteArticleBtn = document.createElement('button');
        deleteArticleBtn.id = 'deleteArticleBtn';
        deleteArticleBtn.className = 'btn btn-danger';
        deleteArticleBtn.innerHTML = '🗑️ Удалить артикул';
        deleteArticleBtn.disabled = true;
        deleteArticleBtn.addEventListener('click', () => {
            deleteArticle(albumSelector.value, articleSelector.value);
        });
        deleteButtonsContainer.appendChild(deleteArticleBtn);
    }

    updateDeleteButtonsState();
}

// --- Функции для работы с XLSX ---
function initXlsxModal() {
    if (!createXlsxBtn || !xlsxModal) return;

    createXlsxBtn.addEventListener('click', showXlsxModal);
    cancelXlsxBtn.addEventListener('click', hideXlsxModal);

    xlsxTemplateSelect.addEventListener('change', function() {
        const separatorGroup = document.getElementById('separatorGroup');
        if (this.value === 'in_cell') {
            separatorGroup.style.display = 'block';
        } else {
            separatorGroup.style.display = 'none';
        }
    });

    generateXlsxBtn.addEventListener('click', generateXlsxFile);

    xlsxModal.addEventListener('click', function(e) {
        if (e.target === xlsxModal) {
            hideXlsxModal();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && xlsxModal.style.display === 'flex') {
            hideXlsxModal();
        }
    });
}

function showXlsxModal() {
    if (!userPermissions.canExport) {
        alert('❌ У вас нет прав для экспорта данных');
        return;
    }

    const selectedAlbum = albumSelector.value;
    if (!selectedAlbum) {
        alert('Сначала выберите альбом');
        return;
    }

    xlsxModal.style.display = 'flex';
    xlsxTemplateSelect.value = 'in_row';
    separatorSelect.value = 'comma';
    document.getElementById('separatorGroup').style.display = 'none';
}

function hideXlsxModal() {
    xlsxModal.style.display = 'none';
}

async function generateXlsxFile() {
    if (!userPermissions.canExport) {
        alert('❌ У вас нет прав для экспорта данных');
        return;
    }

    const selectedAlbum = albumSelector.value;
    const selectedArticle = articleSelector.value || null;
    const exportType = xlsxTemplateSelect.value;
    const separatorType = separatorSelect.value;

    if (!selectedAlbum || !exportType) {
        alert('Заполните все обязательные поля');
        return;
    }

    let separator = ', ';
    if (separatorType === 'newline') {
        separator = '\n';
    }

    const generateBtn = generateXlsxBtn;
    const originalText = generateBtn.innerHTML;

    try {
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span>Создание...</span>';

        const response = await fetch('/api/export-xlsx', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                album_name: selectedAlbum,
                article_name: selectedArticle,
                export_type: exportType,
                separator: separator
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Ошибка при создании файла');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        let filename = `links_${selectedAlbum}`;
        if (selectedArticle) {
            filename += `_${selectedArticle}`;
        }
        filename += '.xlsx';

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        hideXlsxModal();

    } catch (error) {
        console.error('Error generating XLSX:', error);
        alert(`Ошибка при создании файла: ${error.message}`);
    } finally {
        generateBtn.disabled = false;
        generateBtn.innerHTML = originalText;
    }
}



// --- Функции для работы с CSV ---
async function generateCSVFile() {
    console.log('🔄 CSV export function called');

    if (!userPermissions.canExport) {
        alert('❌ У вас нет прав для экспорта данных');
        return;
    }

    const selectedAlbum = albumSelector.value;
    const selectedArticle = articleSelector.value || null;

    console.log('📁 Selected album:', selectedAlbum);
    console.log('📋 Selected article:', selectedArticle);

    if (!selectedAlbum) {
        alert('Сначала выберите альбом');
        return;
    }

    const generateBtn = createCSVBtn;
    const originalText = generateBtn.innerHTML;

    try {
        console.log('🚀 Starting CSV generation request...');
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span>Создание...</span>';

        const response = await fetch('/api/export-csv', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                album_name: selectedAlbum,
                article_name: selectedArticle
                // separator удален - используется жестко закодированный на бэкенде
            })
        });

        console.log('📡 Response status:', response.status);
        console.log('📡 Response ok:', response.ok);

        if (!response.ok) {
            const errorData = await response.json();
            console.error('❌ Server error:', errorData);
            throw new Error(errorData.error || 'Ошибка при создании файла');
        }

        const blob = await response.blob();
        console.log('📄 Blob size:', blob.size);

        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;

        let filename = `links_${selectedAlbum}`;
        if (selectedArticle) {
            filename += `_${selectedArticle}`;
        }
        filename += '.csv';

        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        console.log('✅ CSV file downloaded successfully');

    } catch (error) {
        console.error('❌ Error generating CSV:', error);
        alert(`Ошибка при создании файла: ${error.message}`);
    } finally {
        generateBtn.disabled = false;
        generateBtn.innerHTML = originalText;
    }
}


// Добавить эту функцию для обновления состояния кнопки CSV
function updateCreateCSVButtonState() {
    if (createCSVBtn) {
        createCSVBtn.disabled = !albumSelector.value;
    }
}

function updateCreateXlsxButtonState() {
    if (createXlsxBtn) {
        createXlsxBtn.disabled = !albumSelector.value;
    }
    if (createCSVBtn) {
        createCSVBtn.disabled = !albumSelector.value;
    }
}

// --- Инициализация после загрузки DOM ---
document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM fully loaded and parsed");

    if (!initializeElements()) {
        console.error('Failed to initialize DOM elements. Cannot proceed.');
        return;
    }

    // --- Обработчики Drag and Drop ---
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.add('drag-over'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, () => dropArea.classList.remove('drag-over'), false);
    });

    dropArea.addEventListener('drop', (e) => {
        const file = e.dataTransfer.files[0];
        if (file && file.name.toLowerCase().endsWith('.zip')) {
            droppedFile = file;
            updateUI();
        } else {
            alert('Пожалуйста, выберите ZIP-архив.');
        }
    });

    dropArea.addEventListener('click', function(event) {
        if (event.target && event.target.id === 'browseBtn') {
            console.log("Click event on browseBtn (delegated)!");
            zipFileInput.click();
        }
    });

    zipFileInput.addEventListener('change', () => {
        droppedFile = null;
        updateUI();
    });

    // --- Обработчики для селекторов ---
    albumSelector.addEventListener('change', async function() {
        const selectedAlbum = this.value;
        console.log('Album selected:', selectedAlbum);

        await loadArticles(selectedAlbum);
        clearLinkList();
        updateCreateXlsxButtonState(); // Эта функция теперь обновляет обе кнопки
        updateDeleteButtonsState();

        if (selectedAlbum) {
            setTimeout(() => {
                showFilesForAlbum(selectedAlbum);
            }, 100);
        }
    });

    articleSelector.addEventListener('change', async function() {
        const selectedAlbum = albumSelector.value;
        const selectedArticle = this.value;
        updateDeleteButtonsState();

        if (selectedAlbum) {
            showFilesForAlbum(selectedAlbum, selectedArticle);
        }
    });

    // --- Обработчик отправки формы ---
    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // ПРЯМАЯ ПРОВЕРКА ПРАВ
        if (!userPermissions.canUpload) {
            alert('❌ У вас нет прав для загрузки файлов. Обратитесь к администратору.');
            return;
        }

        if (!zipFileInput || !uploadBtn) {
             console.error('DOM elements for upload not initialized');
             return;
        }
        const file = droppedFile || zipFileInput.files[0];
        if (!file || !file.name.toLowerCase().endsWith('.zip')) {
            alert('Пожалуйста, выберите ZIP-архив.');
            return;
        }

        const formData = new FormData();
        formData.append('zipfile', file, file.name);

        progressContainer.style.display = 'block';
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<span>Загрузка...</span>';

        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                progressBar.style.width = percentComplete + '%';
                progressText.textContent = Math.round(percentComplete) + '%';

                // Показываем оверлей когда загрузка почти завершена
                if (percentComplete > 95) {
                    showLoadingOverlay(
                        'Загрузка завершена.',
                        'Распаковываем файлы и создаем ссылки. Это может занять несколько минут...'
                    );
                }
            }
        });

        xhr.addEventListener('load', function() {
            progressContainer.style.display = 'none';
            showLoadingOverlay(
                'Обработка...',
                'Получаем ответ от сервера...'
            );

            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (!data.error) {
                        let albumName = data.album_name || file.name.replace(/\.zip$/i, '');
                        currentAlbumName = albumName;

                        showLoadingOverlay('Завершение', 'Всё готово!', 'Обновляем список файлов...');

                        setTimeout(() => {
                            showFilesForAlbum(albumName).then(() => {
                                setTimeout(() => {
                                    hideLoadingOverlay();
                                }, 500);
                            });
                        }, 1000);

                        // ОЧИСТКА ФОРМЫ И СБРОС СОСТОЯНИЯ
                        zipFileInput.value = '';
                        droppedFile = null;
                        updateUI(); // Это вызовет сброс кнопки к неактивному состоянию

                        loadAlbums();
                    } else {
                        console.error('Upload failed:', data.error);
                        hideLoadingOverlay();
                        alert(`Ошибка загрузки: ${data.error}`);
                        // В случае ошибки тоже сбрасываем состояние
                        uploadBtn.disabled = false;
                        uploadBtn.innerHTML = '<span>Загрузить архив</span>';
                    }
                } catch (error) {
                    console.error('JSON parse failed:', error);
                    hideLoadingOverlay();
                    alert('Ошибка: получен некорректный ответ от сервера.');
                    // В случае ошибки тоже сбрасываем состояние
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = '<span>Загрузить архив</span>';
                }
            } else {
                console.error('Upload failed with status:', xhr.status);
                hideLoadingOverlay();
                alert(`Ошибка загрузки: HTTP ${xhr.status}`);
                // В случае ошибки тоже сбрасываем состояние
                uploadBtn.disabled = false;
                uploadBtn.innerHTML = '<span>Загрузить архив</span>';
            }
        });

        xhr.addEventListener('error', function() {
            console.error('Upload failed due to network error');
            hideLoadingOverlay();
            alert('Ошибка сети при загрузке файла.');
            progressContainer.style.display = 'none';
            uploadBtn.disabled = false;
            uploadBtn.innerHTML = '<span>Загрузить архив</span>';
        });

        xhr.open('POST', '/upload');
        xhr.send(formData);
    });


    // --- Обработчики Drag and Drop для отдельных изображений ---
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        imageDropArea.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        imageDropArea.addEventListener(eventName, () => imageDropArea.classList.add('drag-over'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        imageDropArea.addEventListener(eventName, () => imageDropArea.classList.remove('drag-over'), false);
    });

    imageDropArea.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            imageFileInput.files = files;
            updateImageUI();
        }
    });

    imageDropArea.addEventListener('click', function(event) {
        if (event.target && event.target.id === 'imageBrowseBtn') {
            imageFileInput.click();
        }
    });

    imageFileInput.addEventListener('change', () => {
        updateImageUI();
    });

    // --- Функция обновления UI для загрузки изображений ---
    function updateImageUI() {
        if (!imageFileInput || !imageDropArea || !uploadImageBtn) {
            console.error('DOM elements not initialized for updateImageUI');
            return;
        }
        const files = imageFileInput.files;
        if (files.length > 0) {
            if (files.length === 1) {
                const file = files[0];
                const fileSize = formatFileSize(file.size);
                imageDropArea.innerHTML = `<p>Выбран файл: <strong>${file.name}</strong></p><p>Размер: ${fileSize}</p><p>Готов к загрузке</p>`;
            } else {
                let totalSize = 0;
                for (let i = 0; i < files.length; i++) {
                    totalSize += files[i].size;
                }
                const totalSizeFormatted = formatFileSize(totalSize);
                imageDropArea.innerHTML = `<p>Выбрано файлов: <strong>${files.length}</strong></p><p>Общий размер: ${totalSizeFormatted}</p><p>Готовы к загрузке</p>`;
            }
            if (userPermissions.canUploadIndividual) {
                uploadImageBtn.disabled = false;
            }
        } else {
            imageDropArea.innerHTML = `<p>Перетащите изображения сюда</p><p>или</p><button type="button" class="btn" id="imageBrowseBtn">Выбрать изображения</button>`;
            uploadImageBtn.disabled = true;
        }
    }

    // --- Обработчик отправки формы загрузки изображений ---
    uploadImageForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // ПРЯМАЯ ПРОВЕРКА ПРАВ
        if (!userPermissions.canUploadIndividual) {
            alert('❌ У вас нет прав для загрузки отдельных файлов. Обратитесь к администратору.');
            return;
        }

        if (!imageFileInput || !uploadImageBtn) {
             console.error('DOM elements for image upload not initialized');
             return;
        }
        const files = imageFileInput.files;
        if (!files || files.length === 0) {
            alert('Пожалуйста, выберите изображения для загрузки.');
            return;
        }

        // Проверяем типы файлов
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            if (!file.type.startsWith('image/')) {
                alert(`Файл ${file.name} не является изображением.`);
                return;
            }
        }

        // Для каждого файла отправляем отдельный запрос
        imageProgressContainer.style.display = 'block';
        uploadImageBtn.disabled = true;
        uploadImageBtn.innerHTML = '<span>Загрузка...</span>';
        
        let uploadedCount = 0;
        const totalFiles = files.length;

        for (let i = 0; i < files.length; i++) {
            const formData = new FormData();
            formData.append('image', files[i], files[i].name);

            try {
                const response = await fetch('/upload-image', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const data = await response.json();
                    if (!data.error) {
                        uploadedCount++;
                        const progress = Math.round((uploadedCount / totalFiles) * 100);
                        imageProgressBar.style.width = progress + '%';
                        imageProgressText.textContent = progress + '%';
                    } else {
                        console.error('Image upload failed:', data.error);
                        alert(`Ошибка загрузки изображения: ${data.error}`);
                    }
                } else {
                    const errorData = await response.json();
                    console.error('Image upload failed with status:', response.status, errorData);
                    alert(`Ошибка загрузки изображения: HTTP ${response.status} - ${errorData.error || 'Неизвестная ошибка'}`);
                }
            } catch (error) {
                console.error('Network error during image upload:', error);
                alert(`Ошибка сети при загрузке изображения: ${error.message}`);
            }
        }

        // После завершения загрузки всех изображений
        imageProgressContainer.style.display = 'none';
        uploadImageBtn.disabled = false;
        uploadImageBtn.innerHTML = '<span>Загрузить изображения</span>';
        
        // Очищаем форму
        imageFileInput.value = '';
        updateImageUI();
        
        // Показываем сообщение о завершении
        if (uploadedCount > 0) {
            alert(`Загрузка завершена! Успешно загружено ${uploadedCount} из ${totalFiles} файлов.`);
            
            // Обновляем список файлов
            if (albumSelector.value) {
                // Обновляем альбом Generic и перезагружаем список артикулов
                await loadArticles('Generic');
                showFilesForAlbum('Generic');
            } else {
                albumSelector.value = 'Generic';
                await loadArticles('Generic');
                showFilesForAlbum('Generic');
            }
        } else {
            alert('Не удалось загрузить ни одного изображения.');
        }
    });


    // --- Обработчик для кнопки "Управление ссылками" ---
    if (manageBtn && uploadCard && manageCard) {
        manageBtn.addEventListener('click', function() {
            console.log("Кнопка 'Управление ссылками' нажата");
            uploadCard.style.display = 'none';
            manageCard.style.display = 'flex';
            clearLinkList();
            loadAlbums();
        });
    } else {
        console.error('Элементы для переключения карточек не найдены');
    }

    // --- Обработчик для кнопки "Назад к загрузке" ---
    if (backToUploadBtn && uploadCard && manageCard) {
        backToUploadBtn.addEventListener('click', function() {
            console.log("Кнопка 'Назад к загрузке' нажата");
            uploadCard.style.display = 'flex';
            manageCard.style.display = 'none';
            clearLinkList();
        });
    } else {
        console.error('Элементы для переключения карточек не найдены');
    }

    // --- Обработчик для кнопки CSV ---
    // ДОБАВЛЯЕМ ОБРАБОТЧИК ПОСЛЕ ИНИЦИАЛИЗАЦИИ ЭЛЕМЕНТОВ
    if (createCSVBtn) {
        console.log("✅ Adding event listener to CSV button");
        createCSVBtn.addEventListener('click', generateCSVFile);
    } else {
        console.error("❌ CSV button not found during initialization");
    }



    // Инициализируем UI
    updateUI();
    clearLinkList();
    initXlsxModal();
    initDeleteButtons();
    updateCreateXlsxButtonState();
    updateDeleteButtonsState();

    // Инициализация проверки сессии
    initSessionCheck();

    // Добавляем очистку интервала при разгрузке страницы
    window.addEventListener('beforeunload', stopStatsAutoRefresh);
});
