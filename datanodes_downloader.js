/**
 * DN Direct Link Downloader - Enterprise Grade Implementation
 * 
 * This module provides a robust, production-ready solution for processing
 * datanodes.to download links with comprehensive error handling, logging,
 * and configuration management.
 * 
 * @author Senior Developer
 * @version 2.0.0
 * @license MIT
 */

'use strict';

const axios = require('axios');
const fs = require('fs').promises;
const fsSync = require('fs');
const readline = require('readline');
const path = require('path');
const { EventEmitter } = require('events');

// ============================================================================
// CONSTANTS & CONFIGURATION
// ============================================================================

const CONFIG = {
    MAX_RETRIES: 3,
    BASE_URL: 'https://datanodes.to/download',
    USER_AGENT: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
    OUTPUT_FILE: 'results.txt',
    CONFIG_FILE: 'downloader_config.json',
    DEFAULT_DELAY: 500,
    REQUEST_TIMEOUT: 30000,
    MAX_CONCURRENT_REQUESTS: 5
};

// ANSI Color codes for terminal output
const COLORS = {
    success: (msg) => `\x1b[32m${msg}\x1b[0m`,
    error: (msg) => `\x1b[31m${msg}\x1b[0m`,
    warn: (msg) => `\x1b[33m${msg}\x1b[0m`,
    info: (msg) => `\x1b[36m${msg}\x1b[0m`,
    debug: (msg) => `\x1b[90m${msg}\x1b[0m`
};

// ============================================================================
// INTERNATIONALIZATION
// ============================================================================

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

// ============================================================================
// CUSTOM ERROR CLASSES
// ============================================================================

/**
 * Base application error class
 */
class AppError extends Error {
    constructor(message, isOperational = true, httpCode = 500) {
        super(message);
        
        // Restore prototype chain
        Object.setPrototypeOf(this, new.target.prototype);
        
        this.name = this.constructor.name;
        this.isOperational = isOperational;
        this.httpCode = httpCode;
        this.timestamp = new Date().toISOString();
        
        Error.captureStackTrace(this, this.constructor);
    }
}

/**
 * Configuration error
 */
class ConfigurationError extends AppError {
    constructor(message) {
        super(message, true, 500);
    }
}

/**
 * Network request error
 */
class NetworkError extends AppError {
    constructor(message, originalError = null) {
        super(message, true, 503);
        this.originalError = originalError;
    }
}

/**
 * Link parsing error
 */
class LinkParsingError extends AppError {
    constructor(message) {
        super(message, true, 400);
    }
}

// ============================================================================
// CENTRALIZED ERROR HANDLER
// ============================================================================

class ErrorHandler {
    constructor() {
        this.isHandlingError = false;
    }

    /**
     * Centralized error handling method
     * @param {Error} error - The error to handle
     * @param {string} context - Context where error occurred
     */
    async handleError(error, context = 'unknown') {
        if (this.isHandlingError) {
            console.error(COLORS.error('Error handler recursion detected, exiting...'));
            process.exit(1);
        }

        this.isHandlingError = true;

        try {
            await this.logError(error, context);
            await this.determineErrorAction(error);
        } catch (handlerError) {
            console.error(COLORS.error(`Error in error handler: ${handlerError.message}`));
            process.exit(1);
        } finally {
            this.isHandlingError = false;
        }
    }

    /**
     * Log error with context
     */
    async logError(error, context) {
        const errorInfo = {
            name: error.name,
            message: error.message,
            stack: error.stack,
            context,
            timestamp: new Date().toISOString(),
            isOperational: error.isOperational || false
        };

        console.error(COLORS.error(`[${context}] ${error.name}: ${error.message}`));
        
        if (process.env.NODE_ENV === 'development') {
            console.error(COLORS.debug(error.stack));
        }
    }

    /**
     * Determine action based on error type
     */
    async determineErrorAction(error) {
        if (!this.isTrustedError(error)) {
            console.error(COLORS.error('Untrusted error detected, shutting down...'));
            process.exit(1);
        }
    }

    /**
     * Check if error is trusted (operational)
     */
    isTrustedError(error) {
        return error.isOperational === true;
    }
}

// Global error handler instance
const errorHandler = new ErrorHandler();

// ============================================================================
// CONFIGURATION MANAGER
// ============================================================================

class ConfigManager {
    constructor() {
        this.configPath = CONFIG.CONFIG_FILE;
        this.defaultConfig = {
            language: 'ru',
            delay: CONFIG.DEFAULT_DELAY,
            maxRetries: CONFIG.MAX_RETRIES,
            requestTimeout: CONFIG.REQUEST_TIMEOUT
        };
    }

    /**
     * Load configuration from file
     * @returns {Promise<Object>} Configuration object
     */
    async loadConfig() {
        try {
            const configData = await fs.readFile(this.configPath, 'utf-8');
            const config = JSON.parse(configData);
            
            // Validate and merge with defaults
            return this.validateAndMergeConfig(config);
        } catch (error) {
            if (error.code === 'ENOENT') {
                console.log(COLORS.warn('Configuration file not found, using defaults'));
                return this.defaultConfig;
            }
            throw new ConfigurationError(`Failed to load configuration: ${error.message}`);
        }
    }

    /**
     * Save configuration to file
     * @param {Object} config - Configuration to save
     * @returns {Promise<boolean>} Success status
     */
    async saveConfig(config) {
        try {
            const validatedConfig = this.validateAndMergeConfig(config);
            await fs.writeFile(this.configPath, JSON.stringify(validatedConfig, null, 2), 'utf-8');
            return true;
        } catch (error) {
            throw new ConfigurationError(`Failed to save configuration: ${error.message}`);
        }
    }

    /**
     * Validate and merge configuration with defaults
     * @param {Object} config - User configuration
     * @returns {Object} Validated and merged configuration
     */
    validateAndMergeConfig(config) {
        const merged = { ...this.defaultConfig, ...config };
        
        // Validate language
        if (!['ru', 'en'].includes(merged.language)) {
            merged.language = this.defaultConfig.language;
        }
        
        // Validate delay
        if (typeof merged.delay !== 'number' || merged.delay < 0) {
            merged.delay = this.defaultConfig.delay;
        }
        
        // Validate maxRetries
        if (typeof merged.maxRetries !== 'number' || merged.maxRetries < 1) {
            merged.maxRetries = this.defaultConfig.maxRetries;
        }
        
        return merged;
    }
}

// ============================================================================
// HTTP CLIENT WITH RETRY LOGIC
// ============================================================================

class HttpClient {
    constructor(config) {
        this.config = config;
        this.axiosInstance = axios.create({
            timeout: config.requestTimeout || CONFIG.REQUEST_TIMEOUT,
            headers: {
                'User-Agent': CONFIG.USER_AGENT,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });

        // Add request/response interceptors for logging
        this.setupInterceptors();
    }

    /**
     * Setup axios interceptors for logging and error handling
     */
    setupInterceptors() {
        this.axiosInstance.interceptors.request.use(
            (config) => {
                console.log(COLORS.debug(`Making request to: ${config.url}`));
                return config;
            },
            (error) => {
                console.error(COLORS.error(`Request error: ${error.message}`));
                return Promise.reject(error);
            }
        );

        this.axiosInstance.interceptors.response.use(
            (response) => {
                console.log(COLORS.debug(`Response received: ${response.status}`));
                return response;
            },
            (error) => {
                console.error(COLORS.error(`Response error: ${error.message}`));
                return Promise.reject(error);
            }
        );
    }

    /**
     * Make HTTP request with retry logic
     * @param {string} url - Request URL
     * @param {Object} options - Request options
     * @param {number} retries - Number of retries
     * @returns {Promise<Object>} Response object
     */
    async request(url, options = {}, retries = 0) {
        try {
            return await this.axiosInstance.request({
                url,
                ...options
            });
        } catch (error) {
            if (retries < this.config.maxRetries) {
                const delay = Math.pow(2, retries) * 1000; // Exponential backoff
                console.log(COLORS.warn(`Retrying request (${retries + 1}/${this.config.maxRetries}) in ${delay}ms`));
                await this.sleep(delay);
                return this.request(url, options, retries + 1);
            }
            
            throw new NetworkError(`Request failed after ${this.config.maxRetries} retries: ${error.message}`, error);
        }
    }

    /**
     * Sleep utility
     * @param {number} ms - Milliseconds to sleep
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// ============================================================================
// LINK PROCESSOR
// ============================================================================

class LinkProcessor {
    constructor(httpClient, config) {
        this.httpClient = httpClient;
        this.config = config;
        this.eventEmitter = new EventEmitter();
    }

    /**
     * Parse datanodes link to extract file ID and name
     * @param {string} link - Datanodes link
     * @returns {Object} Parsed link data
     */
    parseLink(link) {
        try {
            if (!link || typeof link !== 'string') {
                throw new LinkParsingError('Link must be a non-empty string');
            }

            if (!link.includes('datanodes.to')) {
                throw new LinkParsingError('Invalid datanodes link format');
            }

            const urlParts = link.split('/');
            if (urlParts.length < 5) {
                throw new LinkParsingError('Link does not contain required parts');
            }

            const fileId = urlParts[3];
            const fileName = urlParts[4];

            if (!fileId || !fileName) {
                throw new LinkParsingError('Missing file ID or name in link');
            }

            return { fileId, fileName };
        } catch (error) {
            if (error instanceof LinkParsingError) {
                throw error;
            }
            throw new LinkParsingError(`Link parsing failed: ${error.message}`);
        }
    }

    /**
     * Make first POST request to initiate download
     * @param {string} fileId - File ID
     * @param {string} fileName - File name
     * @returns {Promise<Object>} Response object
     */
    async makeFirstRequest(fileId, fileName) {
        const postData = {
            op: 'download1',
            usr_login: '',
            id: fileId,
            fname: fileName,
            referer: '',
            method_free: 'Free Download >>'
        };

        return this.httpClient.request(CONFIG.BASE_URL, {
            method: 'POST',
            data: new URLSearchParams(postData)
        });
    }

    /**
     * Make second POST request to get redirect URL
     * @param {string} fileId - File ID
     * @returns {Promise<Object>} Response object
     */
    async makeSecondRequest(fileId) {
        const postData = {
            op: 'download2',
            id: fileId,
            rand: '',
            referer: CONFIG.BASE_URL,
            method_free: 'Free Download >>',
            method_premium: '',
            g_captch__a: 1
        };

        return this.httpClient.request(CONFIG.BASE_URL, {
            method: 'POST',
            data: new URLSearchParams(postData),
            maxRedirects: 0,
            validateStatus: (status) => status === 200
        });
    }

    /**
     * Process single link
     * @param {string} link - Link to process
     * @returns {Promise<string|null>} Redirect URL or null if failed
     */
    async processLink(link) {
        try {
            this.eventEmitter.emit('linkProcessingStart', link);
            
            const { fileId, fileName } = this.parseLink(link);
            
            await this.makeFirstRequest(fileId, fileName);
            const secondResponse = await this.makeSecondRequest(fileId);
            
            const redirectUrl = secondResponse.data;
            if (!redirectUrl || !redirectUrl.url) {
                throw new Error('No redirect URL found in response');
            }

            this.eventEmitter.emit('linkProcessingSuccess', link);
            return decodeURIComponent(redirectUrl.url).replace(/[\r\n\t]/g, '').trim();
            
        } catch (error) {
            this.eventEmitter.emit('linkProcessingError', { link, error });
            throw error;
        }
    }
}

// ============================================================================
// DOWNLOAD MANAGER
// ============================================================================

class DownloadManager {
    constructor(config, language) {
        this.config = config;
        this.language = language;
        this.translations = TRANSLATIONS[language];
        this.httpClient = new HttpClient(config);
        this.linkProcessor = new LinkProcessor(this.httpClient, config);
        this.results = [];
        this.failedLinks = [];
        this.eventEmitter = this.linkProcessor.eventEmitter;
        
        this.setupEventListeners();
    }

    /**
     * Setup event listeners for link processing
     */
    setupEventListeners() {
        this.eventEmitter.on('linkProcessingStart', (link) => {
            console.log(COLORS.info(`${this.translations.linkProcessingStart} ${link}`));
        });

        this.eventEmitter.on('linkProcessingSuccess', (link) => {
            console.log(COLORS.success(`${this.translations.linkProcessingSuccess} ${link}`));
        });

        this.eventEmitter.on('linkProcessingError', ({ link, error }) => {
            console.error(COLORS.error(`${this.translations.linkProcessingError} ${link}: ${error.message}`));
        });
    }

    /**
     * Process multiple links with concurrency control
     * @param {string[]} links - Array of links to process
     * @returns {Promise<Object>} Processing results
     */
    async processLinks(links) {
        if (!Array.isArray(links) || links.length === 0) {
            console.log(COLORS.warn(this.translations.noLinks));
            return { results: [], failedLinks: [] };
        }

        console.log(COLORS.info(`${this.translations.processingStart} ${links.length} ${this.translations.of} ${this.translations.attempts}...`));

        const results = [];
        const failedLinks = [];

        // Process links with controlled concurrency
        for (let i = 0; i < links.length; i += CONFIG.MAX_CONCURRENT_REQUESTS) {
            const batch = links.slice(i, i + CONFIG.MAX_CONCURRENT_REQUESTS);
            const batchPromises = batch.map(async (link, index) => {
                const globalIndex = i + index;
                console.log(COLORS.info(`${this.translations.processingLink} ${globalIndex + 1} ${this.translations.of} ${links.length}: ${link}`));
                
                try {
                    const result = await this.linkProcessor.processLink(link);
                    return { success: true, link, result };
                } catch (error) {
                    return { success: false, link, error: error.message };
                }
            });

            const batchResults = await Promise.all(batchPromises);
            
            batchResults.forEach(({ success, link, result, error }) => {
                if (success) {
                    results.push(result);
                } else {
                    failedLinks.push({ link, error });
                }
            });

            // Add delay between batches
            if (i + CONFIG.MAX_CONCURRENT_REQUESTS < links.length) {
                await this.sleep(this.config.delay);
            }
        }

        this.results = results;
        this.failedLinks = failedLinks;

        await this.saveResults();
        this.printSummary();

        return { results, failedLinks };
    }

    /**
     * Save results to file
     * @returns {Promise<void>}
     */
    async saveResults() {
        try {
            await fs.writeFile(CONFIG.OUTPUT_FILE, this.results.join('\n'), 'utf-8');
            console.log(COLORS.success(`${this.translations.resultsSaved} ${CONFIG.OUTPUT_FILE}`));
        } catch (error) {
            throw new Error(`${this.translations.saveError} ${error.message}`);
        }
    }

    /**
     * Print processing summary
     */
    printSummary() {
        console.log(COLORS.info(`\n${this.translations.summary}`));
        console.log(COLORS.success(`${this.translations.successCount} ${this.results.length} ${this.translations.attempts}`));
        console.log(COLORS.error(`${this.translations.failedCount} ${this.failedLinks.length} ${this.translations.attempts}`));

        if (this.failedLinks.length > 0) {
            console.log(COLORS.warn(`\n${this.translations.failedLinks}`));
            this.failedLinks.forEach(({ link, error }, index) => {
                console.log(`${index + 1}. ${link} - ${error}`);
            });
        }

        console.log(COLORS.success(`\n${this.translations.processingComplete}`));
    }

    /**
     * Sleep utility
     * @param {number} ms - Milliseconds to sleep
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// ============================================================================
// USER INPUT HANDLER
// ============================================================================

class UserInputHandler {
    constructor(language) {
        this.language = language;
        this.translations = TRANSLATIONS[language];
        this.rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout
        });
    }

    /**
     * Get links from user input
     * @returns {Promise<string[]>} Array of links
     */
    async getLinks() {
        return new Promise((resolve) => {
            const links = [];
            
            console.log(this.translations.enterLinks);
            this.rl.prompt();

            this.rl.on('line', (line) => {
                const trimmedLine = line.trim();
                
                if (trimmedLine === '') {
                    this.rl.close();
                    resolve(links);
                } else {
                    if (this.isValidLink(trimmedLine)) {
                        links.push(trimmedLine);
                        console.log(COLORS.success(`${this.translations.linkAdded} ${trimmedLine}`));
                    } else {
                        console.log(COLORS.warn(`${this.translations.invalidLink} ${trimmedLine}`));
                    }
                    this.rl.prompt();
                }
            });
        });
    }

    /**
     * Validate link format
     * @param {string} link - Link to validate
     * @returns {boolean} Validation result
     */
    isValidLink(link) {
        return link && typeof link === 'string' && link.includes('datanodes.to');
    }

    /**
     * Close readline interface
     */
    close() {
        this.rl.close();
    }
}

// ============================================================================
// APPLICATION SETUP
// ============================================================================

class AppSetup {
    constructor() {
        this.configManager = new ConfigManager();
    }

    /**
     * Select language interactively
     * @returns {Promise<string>} Selected language
     */
    async selectLanguage() {
        return new Promise((resolve) => {
            const rl = readline.createInterface({
                input: process.stdin,
                output: process.stdout
            });

            console.log(COLORS.info(TRANSLATIONS.ru.languageSelect));
            console.log(TRANSLATIONS.ru.languageOptions);

            rl.question('> ', (answer) => {
                rl.close();
                const choice = answer.trim();
                
                if (choice === '1') {
                    resolve('ru');
                } else if (choice === '2') {
                    resolve('en');
                } else {
                    console.log(COLORS.warn(TRANSLATIONS.ru.invalidChoice));
                    resolve(this.selectLanguage());
                }
            });
        });
    }

    /**
     * Setup delay configuration
     * @param {string} language - Current language
     * @returns {Promise<number>} Delay in milliseconds
     */
    async setupDelay(language) {
        const translations = TRANSLATIONS[language];
        const rl = readline.createInterface({
            input: process.stdin,
            output: process.stdout
        });

        return new Promise((resolve) => {
            const askForDelay = () => {
                rl.question(`${translations.useDefaultDelay} `, (answer) => {
                    const choice = answer.trim().toLowerCase();
                    
                    if (choice === 'y' || choice === 'yes' || choice === 'да') {
                        rl.close();
                        resolve(CONFIG.DEFAULT_DELAY);
                    } else if (choice === 'n' || choice === 'no' || choice === 'нет') {
                        rl.question(`${translations.customDelay} `, (delayAnswer) => {
                            const delay = parseInt(delayAnswer.trim());
                            rl.close();
                            
                            if (isNaN(delay) || delay < 0) {
                                console.log(COLORS.warn(translations.invalidDelay));
                                resolve(CONFIG.DEFAULT_DELAY);
                            } else {
                                resolve(delay);
                            }
                        });
                    } else {
                        console.log(COLORS.warn(translations.invalidChoice));
                        askForDelay();
                    }
                });
            };

            askForDelay();
        });
    }

    /**
     * Check existing configuration
     * @param {string} language - Current language
     * @returns {Promise<Object>} Configuration object
     */
    async checkExistingConfig(language) {
        const translations = TRANSLATIONS[language];
        const config = await this.configManager.loadConfig();
        
        if (config.delay !== undefined) {
            console.log(COLORS.info(`${translations.currentDelay} ${config.delay}ms`));
            
            const rl = readline.createInterface({
                input: process.stdin,
                output: process.stdout
            });

            return new Promise((resolve) => {
                rl.question(`${translations.changeDelay} `, (answer) => {
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

    /**
     * Initialize application
     * @returns {Promise<Object>} Initialized configuration
     */
    async initialize() {
        console.log(COLORS.info(TRANSLATIONS.ru.title));
        console.log(COLORS.info(TRANSLATIONS.ru.separator));
        console.log(COLORS.info(TRANSLATIONS.ru.welcome));
        console.log('');

        const language = await this.selectLanguage();
        const delay = await this.checkExistingConfig(language);

        const config = { language, delay };
        if (await this.configManager.saveConfig(config)) {
            console.log(COLORS.success(TRANSLATIONS.ru.configSaved));
        }

        return { language, delay };
    }
}

// ============================================================================
// GLOBAL ERROR HANDLERS
// ============================================================================

// Handle unhandled promise rejections
process.on('unhandledRejection', (reason, promise) => {
    console.error(COLORS.error('Unhandled Promise Rejection:'));
    console.error(COLORS.error(reason));
    errorHandler.handleError(reason instanceof Error ? reason : new Error(String(reason)), 'unhandledRejection');
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
    console.error(COLORS.error('Uncaught Exception:'));
    errorHandler.handleError(error, 'uncaughtException');
});

// ============================================================================
// MAIN APPLICATION
// ============================================================================

/**
 * Main application function
 */
async function main() {
    try {
        const appSetup = new AppSetup();
        const { language, delay } = await appSetup.initialize();

        const inputHandler = new UserInputHandler(language);
        const links = await inputHandler.getLinks();

        if (links.length > 0) {
            const config = { delay, maxRetries: CONFIG.MAX_RETRIES, requestTimeout: CONFIG.REQUEST_TIMEOUT };
            const downloadManager = new DownloadManager(config, language);
            await downloadManager.processLinks(links);
        } else {
            console.log(COLORS.warn(TRANSLATIONS[language].noLinksEntered));
        }

    } catch (error) {
        await errorHandler.handleError(error, 'main');
        process.exit(1);
    }
}

// ============================================================================
// MODULE EXPORTS
// ============================================================================

module.exports = {
    DownloadManager,
    UserInputHandler,
    ConfigManager,
    AppSetup,
    LinkProcessor,
    HttpClient,
    ErrorHandler,
    AppError,
    ConfigurationError,
    NetworkError,
    LinkParsingError,
    CONFIG,
    TRANSLATIONS
};

// ============================================================================
// APPLICATION ENTRY POINT
// ============================================================================

if (require.main === module) {
    main().catch(async (error) => {
        await errorHandler.handleError(error, 'entry');
        process.exit(1);
    });
}
