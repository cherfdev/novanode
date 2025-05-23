const axios = require('axios'); // Импортируем Axios для HTTP запросов
const fs = require('fs'); // Импортируем fs для работы с файловой системой
const readline = require('readline'); // Импортируем readline для ввода данных с клавиатуры


const colorCodes = {
    success: (msg) => `\x1b[32m${msg}\x1b[0m`,
    error: (msg) => `\x1b[31m${msg}\x1b[0m`,
    warn: (msg) => `\x1b[33m${msg}\x1b[0m`
};


const MAX_RETRIES = 3;

const failedLinks = []; // Список ссылок, которые не удалось обработать

// Функция для обработки одной ссылки
async function processLink(link, attempt = 1) {
    try {
        // Извлечение ID и имени файла из ссылки
        const urlParts = link.split('/');
        const fileId = urlParts[3];
        const fileName = urlParts[4];

        // Данные для первого POST запроса
        const firstPostData = {
            op: 'download1',
            usr_login: '',
            id: fileId,
            fname: fileName,
            referer: '',
            method_free: 'Free Download >>'
        };

        console.log(`(${attempt}) Начинается обработка ссылки: ${link}`);

        // Первый POST запрос
        const firstResponse = await axios.post('https://datanodes.to/download', new URLSearchParams(firstPostData), {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36'
            }
        });

        // Проверка успешности первого запроса
        if (firstResponse.status !== 200) {
            throw new Error(`Первый POST запрос завершился с ошибкой: ${firstResponse.status}`);
        }

        // Данные для второго POST запроса
        const secondPostData = {
            op: 'download2',
            id: fileId,
            rand: '',
            referer: 'https://datanodes.to/download',
            method_free: 'Free Download >>',
            method_premium: '',
            dl: 1
        };

        // Второй POST запрос
        const secondResponse = await axios.post('https://datanodes.to/download', new URLSearchParams(secondPostData), {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            maxRedirects: 0, // Чтобы поймать редирект без его выполнения
            validateStatus: function (status) {
                return status === 200; // Принимаем только статус 200
            }
        });

        // Извлекаем URL перенаправления из заголовка 'Location'
        const redirectUrl = secondResponse.data;

        if (!redirectUrl || !redirectUrl.url) {

            throw new Error('Не удалось найти URL перенаправления в ответе.');

        }

        console.log(colorCodes.success(`Обработка ссылки завершена: ${link}`));
        return redirectUrl.url
    } catch (error) {

        console.error(colorCodes.error(`Ошибка при обработке ссылки ${link} (попытка ${attempt}): ${error.message}`));

        if (attempt < MAX_RETRIES) {
            console.log(colorCodes.warn(`Повторная попытка (${attempt + 1}) для ссылки: ${link}`));
            return processLink(link, attempt + 1);
        } else {
            console.error(`Не удалось обработать ссылку после ${MAX_RETRIES} попыток: ${link}`);
            failedLinks.push(link);
            return null;

        }
    }
}

// Основная функция для обработки массива ссылок
async function processLinks(links) {
    const results = [];

    console.log(`Начало обработки ${links.length} ссылок...`);

    // Обрабатываем каждую ссылку
    console.log(`Начало обработки ${links.length} ссылок...`);

    for (const [index, link] of links.entries()) {
        console.log(`Обрабатывается ссылка ${index + 1} из ${links.length}: ${link}`);
        const result = await processLink(link);
        if (result) {
			result_ = decodeURIComponent(result);
            results.push(result_.replace(/[\r\n\t]/g, '').trim());
        }
    }

    // Сохраняем результаты в файл
    fs.writeFileSync('results.txt', results.join('\n'), 'utf-8');
    console.log(colorCodes.success('Ссылки перенаправления сохранены в файл results.txt'));
    if (failedLinks.length > 0) {
        console.log('Не удалось обработать следующие ссылки:');
        failedLinks.forEach(link => console.log(link));
    }
    console.log('Обработка всех ссылок завершена.');
}

// Настройка интерфейса readline для ввода данных с клавиатуры
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: 'Введите ссылки по одной на строке (пустая строка для завершения):\n'
});

// Массив для хранения введенных ссылок
const links = [];

// Запрос ввода от пользователя
rl.prompt();

rl.on('line', (line) => {
    if (line.trim() === '') { // Если строка пустая, заканчиваем ввод
        rl.close();
    } else {
        links.push(line.trim()); // Добавляем ссылку в массив
        rl.prompt(); // Продолжаем запрос ввода
    }
}).on('close', () => {
    if (links.length > 0) {
        processLinks(links); // Запуск обработки введенных ссылок
    } else {
        console.log('Нет введенных ссылок для обработки.');
    }
});
