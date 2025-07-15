const axios = require('axios');
const fs = require('fs');
const readline = require('readline');
const path = require('path');

// Константы
const CONFIG = {
    MAX_RETRIES: 3,
    BASE_URL: 'https://datanodes.to/download',
    USER_AGENT: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    OUTPUT_FILE: 'results.txt',
    CONFIG_FILE: 'downloader_config.json',
    DEFAULT_DELAY: 500
};

// Цветовые коды для консоли
const COLORS = {
    success: (msg) => `\x1b[32m${msg}\x1b[0m`,
    error: (msg) => `\x1b[31m${msg}\x1b[0m`,
    warn: (msg) => `\x1b[33m${msg}\x1b[0m`,
    info: (msg) => `\x1b[36m${msg}\x1b[0m`
};

// Локализация
const TRANSLATIONS = {
    ru: {
        title: '🔗 DN Direct Link Downloader',
        separator: '=====================================',
        languageSelect: 'Выберите язык / Select language:',
        languageOptions: '1. Русский\n2. English',
        invalidChoice: 'Неверный выбор. Попробуйте снова.',
        welcome: 'Добро пожаловать в DN Direct Link Downloader!',
        configNotFound: 'Конфигурационный файл не найден.',
        useDefaultDelay: 'Использовать задержку по умолчанию (500мс)? (y/n):',
        customDelay: 'Введите кастомную задержку в миллисекундах:',
        invalidDelay: 'Неверное значение. Используется значение по умолчанию.',
        configSaved: 'Конфигурация сохранена.',
        currentDelay: 'Текущая задержка между запросами:',
        changeDelay: 'Хотите изменить задержку? (y/n):',
        enterLinks: 'Введите ссылки по одной на строке (пустая строка для завершения):',
        linkAdded: '✓ Добавлена ссылка:',
        invalidLink: '⚠ Некорректная ссылка:',
        noLinks: 'Нет ссылок для обработки',
        processingStart: '🚀 Начало обработки',
        processingLink: '📥 Обрабатывается ссылка',
        of: 'из',
        linkProcessingStart: 'Начинается обработка ссылки:',
        linkProcessingSuccess: '✓ Обработка ссылки завершена:',
        linkProcessingError: '✗ Ошибка при обработке ссылки',
        retryAttempt: '🔄 Повторная попытка',
        maxRetriesReached: '❌ Не удалось обработать ссылку после',
        attempts: 'попыток:',
        firstRequestError: 'Первый POST запрос завершился с ошибкой:',
        secondRequestError: 'Второй POST запрос завершился с ошибкой:',
        noRedirectUrl: 'Не удалось найти URL перенаправления в ответе',
        parsingError: 'Ошибка парсинга ссылки:',
        invalidLinkFormat: 'Неверный формат ссылки',
        resultsSaved: '💾 Ссылки перенаправления сохранены в файл',
        saveError: 'Ошибка при сохранении файла:',
        summary: '📊 ИТОГОВАЯ СТАТИСТИКА:',
        successCount: '✅ Успешно обработано:',
        failedCount: '❌ Не удалось обработать:',
        failedLinks: 'Не удалось обработать следующие ссылки:',
        processingComplete: '🎉 Обработка всех ссылок завершена!',
        noLinksEntered: 'Нет введенных ссылок для обработки.',
        criticalError: 'Критическая ошибка:',
        unexpectedError: 'Неожиданная ошибка:'
    },
    en: {
        title: '🔗 DN Direct Link Downloader',
        separator: '=====================================',
        languageSelect: 'Select language / Выберите язык:',
        languageOptions: '1. English\n2. Русский',
        invalidChoice: 'Invalid choice. Try again.',
        welcome: 'Welcome to DN Direct Link Downloader!',
        configNotFound: 'Configuration file not found.',
        useDefaultDelay: 'Use default delay (500ms)? (y/n):',
        customDelay: 'Enter custom delay in milliseconds:',
        invalidDelay: 'Invalid value. Using default value.',
        configSaved: 'Configuration saved.',
        currentDelay: 'Current delay between requests:',
        changeDelay: 'Do you want to change the delay? (y/n):',
        enterLinks: 'Enter links one per line (empty line to finish):',
        linkAdded: '✓ Link added:',
        invalidLink: '⚠ Invalid link:',
        noLinks: 'No links to process',
        processingStart: '🚀 Starting processing of',
        processingLink: '📥 Processing link',
        of: 'of',
        linkProcessingStart: 'Starting link processing:',
        linkProcessingSuccess: '✓ Link processing completed:',
        linkProcessingError: '✗ Error processing link',
        retryAttempt: '🔄 Retry attempt',
        maxRetriesReached: '❌ Failed to process link after',
        attempts: 'attempts:',
        firstRequestError: 'First POST request failed with error:',
        secondRequestError: 'Second POST request failed with error:',
        noRedirectUrl: 'Could not find redirect URL in response',
        parsingError: 'Link parsing error:',
        invalidLinkFormat: 'Invalid link format',
        resultsSaved: '💾 Redirect links saved to file',
        saveError: 'Error saving file:',
        summary: '📊 FINAL STATISTICS:',
        successCount: '✅ Successfully processed:',
        failedCount: '❌ Failed to process:',
        failedLinks: 'Failed to process the following links:',
        processingComplete: '🎉 All links processing completed!',
        noLinksEntered: 'No links entered for processing.',
        criticalError: 'Critical error:',
        unexpectedError: 'Unexpected error:'
    }
};

// Класс для управления конфигурацией
class ConfigManager {
    constructor() {
        this.configPath = CONFIG.CONFIG_FILE;
        this.defaultConfig = {
            language: 'ru',
            delay: CONFIG.DEFAULT_DELAY
        };
    }

    // Загрузка конфигурации
    loadConfig() {
        try {
            if (fs.existsSync(this.configPath)) {
                const configData = fs.readFileSync(this.configPath, 'utf-8');
                return JSON.parse(configData);
            }
        } catch (error) {
            console.log(COLORS.warn('Error loading config, using defaults'));
        }
        return this.defaultConfig;
    }

    // Сохранение конфигурации
    saveConfig(config) {
        try {
            fs.writeFileSync(this.configPath, JSON.stringify(config, null, 2), 'utf-8');
            return true;
        } catch (error) {
            console.error(COLORS.error(`Error saving config: ${error.message}`));
            return false;
        }
    }
}

// Класс для обработки ссылок
class DatanodesDownloader {
    constructor(language, delay) {
        this.failedLinks = [];
        this.results = [];
        this.language = language;
        this.delay = delay;
        this.t = TRANSLATIONS[language];
    }

    // Извлечение ID и имени файла из ссылки
    parseLink(link) {
        try {
            const urlParts = link.split('/');
            if (urlParts.length < 5) {
                throw new Error(this.t.invalidLinkFormat);
            }
            return {
                fileId: urlParts[3],
                fileName: urlParts[4]
            };
        } catch (error) {
            throw new Error(`${this.t.parsingError} ${error.message}`);
        }
    }

    // Первый POST запрос
    async makeFirstRequest(fileId, fileName) {
        const postData = {
            op: 'download1',
            usr_login: '',
            id: fileId,
            fname: fileName,
            referer: '',
            method_free: 'Free Download >>'
        };

        const response = await axios.post(CONFIG.BASE_URL, new URLSearchParams(postData), {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': CONFIG.USER_AGENT
            },
            timeout: 30000
        });

        if (response.status !== 200) {
            throw new Error(`${this.t.firstRequestError} ${response.status}`);
        }

        return response;
    }

    // Второй POST запрос
    async makeSecondRequest(fileId) {
        const postData = {
            op: 'download2',
            id: fileId,
            rand: '',
            referer: CONFIG.BASE_URL,
            method_free: 'Free Download >>',
            method_premium: '',
            dl: 1
        };

        const response = await axios.post(CONFIG.BASE_URL, new URLSearchParams(postData), {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': CONFIG.USER_AGENT
            },
            maxRedirects: 0,
            validateStatus: (status) => status === 200,
            timeout: 30000
        });

        return response;
    }

    // Обработка одной ссылки
    async processLink(link, attempt = 1) {
        try {
            console.log(COLORS.info(`(${attempt}) ${this.t.linkProcessingStart} ${link}`));

            const { fileId, fileName } = this.parseLink(link);
            await this.makeFirstRequest(fileId, fileName);
            const secondResponse = await this.makeSecondRequest(fileId);
            const redirectUrl = secondResponse.data;

            if (!redirectUrl || !redirectUrl.url) {
                throw new Error(this.t.noRedirectUrl);
            }

            console.log(COLORS.success(`${this.t.linkProcessingSuccess} ${link}`));
            return redirectUrl.url;

        } catch (error) {
            console.error(COLORS.error(`${this.t.linkProcessingError} ${link} (${this.t.attempts} ${attempt}): ${error.message}`));

            if (attempt < CONFIG.MAX_RETRIES) {
                console.log(COLORS.warn(`${this.t.retryAttempt} (${attempt + 1}) ${this.t.of} ${link}`));
                await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
                return this.processLink(link, attempt + 1);
            } else {
                console.error(COLORS.error(`${this.t.maxRetriesReached} ${CONFIG.MAX_RETRIES} ${this.t.attempts} ${link}`));
                this.failedLinks.push(link);
                return null;
            }
        }
    }

    // Обработка массива ссылок
    async processLinks(links) {
        if (!Array.isArray(links) || links.length === 0) {
            console.log(COLORS.warn(this.t.noLinks));
            return;
        }

        console.log(COLORS.info(`${this.t.processingStart} ${links.length} ${this.t.of} ${this.t.attempts}...`));

        for (const [index, link] of links.entries()) {
            console.log(COLORS.info(`${this.t.processingLink} ${index + 1} ${this.t.of} ${links.length}: ${link}`));
            
            const result = await this.processLink(link);
            if (result) {
                const cleanResult = decodeURIComponent(result).replace(/[\r\n\t]/g, '').trim();
                this.results.push(cleanResult);
            }

            if (index < links.length - 1) {
                await new Promise(resolve => setTimeout(resolve, this.delay));
            }
        }

        this.saveResults();
        this.printSummary();
    }

    // Сохранение результатов
    saveResults() {
        try {
            fs.writeFileSync(CONFIG.OUTPUT_FILE, this.results.join('\n'), 'utf-8');
            console.log(COLORS.success(`${this.t.resultsSaved} ${CONFIG.OUTPUT_FILE}`));
        } catch (error) {
            console.error(COLORS.error(`${this.t.saveError} ${error.message}`));
        }
    }

    // Вывод итоговой статистики
    printSummary() {
        console.log(COLORS.info(`\n${this.t.summary}`));
        console.log(COLORS.success(`${this.t.successCount} ${this.results.length} ${this.t.attempts}`));
        console.log(COLORS.error(`${this.t.failedCount} ${this.failedLinks.length} ${this.t.attempts}`));

        if (this.failedLinks.length > 0) {
            console.log(COLORS.warn(`\n${this.t.failedLinks}`));
            this.failedLinks.forEach((link, index) => {
                console.log(`${index + 1}. ${link}`);
            });
        }

        console.log(COLORS.success(`\n${this.t.processingComplete}`));
    }
}

// Класс для работы с пользовательским вводом
class UserInputHandler {
    constructor(language) {
        this.language = language;
        this.t = TRANSLATIONS[language];
        this.rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout
        });
        this.links = [];
    }

    // Получение ссылок от пользователя
    async getLinks() {
        return new Promise((resolve) => {
            this.rl.setPrompt(`${this.t.enterLinks}\n`);
            this.rl.prompt();

            this.rl.on('line', (line) => {
                const trimmedLine = line.trim();
                
                if (trimmedLine === '') {
                    this.rl.close();
                    resolve(this.links);
                } else {
                    if (this.isValidLink(trimmedLine)) {
                        this.links.push(trimmedLine);
                        console.log(COLORS.success(`${this.t.linkAdded} ${trimmedLine}`));
                    } else {
                        console.log(COLORS.warn(`${this.t.invalidLink} ${trimmedLine}`));
                    }
                    this.rl.prompt();
                }
            });
        });
    }

    // Простая валидация ссылки
    isValidLink(link) {
        return link.includes('datanodes.to');
    }

    // Закрытие интерфейса
    close() {
        this.rl.close();
    }
}

// Класс для настройки приложения
class AppSetup {
    constructor() {
        this.configManager = new ConfigManager();
    }

    // Выбор языка
    async selectLanguage() {
        return new Promise((resolve) => {
            const rl = readline.createInterface({
                input: process.stdin,
                output: process.stdout
            });

            console.log(COLORS.info(this.getTranslation('languageSelect')));
            console.log(this.getTranslation('languageOptions'));

            rl.question('> ', (answer) => {
                rl.close();
                const choice = answer.trim();
                
                if (choice === '1') {
                    resolve('ru');
                } else if (choice === '2') {
                    resolve('en');
                } else {
                    console.log(COLORS.warn(this.getTranslation('invalidChoice')));
                    resolve(this.selectLanguage());
                }
            });
        });
    }

    // Настройка задержки
    async setupDelay(language) {
        const t = TRANSLATIONS[language];
        const rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout
        });

        return new Promise((resolve) => {
            const askForDelay = () => {
                rl.question(`${t.useDefaultDelay} `, (answer) => {
                    const choice = answer.trim().toLowerCase();
                    
                    if (choice === 'y' || choice === 'yes' || choice === 'да') {
                        rl.close();
                        resolve(CONFIG.DEFAULT_DELAY);
                    } else if (choice === 'n' || choice === 'no' || choice === 'нет') {
                        rl.question(`${t.customDelay} `, (delayAnswer) => {
                            const delay = parseInt(delayAnswer.trim());
                            rl.close();
                            
                            if (isNaN(delay) || delay < 0) {
                                console.log(COLORS.warn(t.invalidDelay));
                                resolve(CONFIG.DEFAULT_DELAY);
                            } else {
                                resolve(delay);
                            }
                        });
                    } else {
                        console.log(COLORS.warn(t.invalidChoice));
                        askForDelay();
                    }
                });
            };

            askForDelay();
        });
    }

    // Проверка существующей конфигурации
    async checkExistingConfig(language) {
        const t = TRANSLATIONS[language];
        const config = this.configManager.loadConfig();
        
        if (config.delay !== undefined) {
            console.log(COLORS.info(`${t.currentDelay} ${config.delay}ms`));
            
            const rl = readline.createInterface({
                input: process.stdin,
                output: process.stdout
            });

            return new Promise((resolve) => {
                rl.question(`${t.changeDelay} `, (answer) => {
                    rl.close();
                    const choice = answer.trim().toLowerCase();
                    
                    if (choice === 'y' || choice === 'yes' || choice === 'да') {
                        resolve(this.setupDelay(language));
                    } else {
                        resolve(config.delay);
                    }
                });
            });
        } else {
            return this.setupDelay(language);
        }
    }

    // Получение перевода
    getTranslation(key) {
        return TRANSLATIONS.ru[key] || key;
    }

    // Инициализация приложения
    async initialize() {
        console.log(COLORS.info(this.getTranslation('title')));
        console.log(COLORS.info(this.getTranslation('separator')));
        console.log(COLORS.info(this.getTranslation('welcome')));
        console.log('');

        const language = await this.selectLanguage();
        const delay = await this.checkExistingConfig(language);

        const config = { language, delay };
        if (this.configManager.saveConfig(config)) {
            console.log(COLORS.success(this.getTranslation('configSaved')));
        }

        return { language, delay };
    }
}

// Основная функция
async function main() {
    try {
        const appSetup = new AppSetup();
        const { language, delay } = await appSetup.initialize();

        const inputHandler = new UserInputHandler(language);
        const links = await inputHandler.getLinks();

        if (links.length > 0) {
            const downloader = new DatanodesDownloader(language, delay);
            await downloader.processLinks(links);
        } else {
            console.log(COLORS.warn(TRANSLATIONS[language].noLinksEntered));
        }

    } catch (error) {
        console.error(COLORS.error(`${TRANSLATIONS.ru.criticalError} ${error.message}`));
        process.exit(1);
    }
}

// Запуск программы
if (require.main === module) {
    main().catch(error => {
        console.error(COLORS.error(`${TRANSLATIONS.ru.unexpectedError} ${error.message}`));
        process.exit(1);
    });
}

module.exports = { DatanodesDownloader, UserInputHandler, ConfigManager, AppSetup };
