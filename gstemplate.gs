const APP_CONFIG = {
  spreadsheetName: 'лист «Плоская_таблица»',
  defaultPage: 'dashboard',
  pages: {
    dashboard: { key: 'dashboard', title: 'Финансовый дашборд', menuTitle: 'Дэшборд', file: 'dashboard', description: 'Сводная оценка финансового состояния компании' },
    money: { key: 'money', title: 'Деньги', menuTitle: 'Деньги', file: 'money', description: 'Денежные потоки и обязательные платежи' },
    capital: { key: 'capital', title: 'Капитал', menuTitle: 'Капитал', file: 'capital', description: 'Активы, обязательства и долговая нагрузка' },
    profit: { key: 'profit', title: 'Прибыль', menuTitle: 'Прибыль', file: 'profit', description: 'Выручка, прибыль и динамика результатов' },
    risks: { key: 'risks', title: 'Риски и связи', menuTitle: 'Риски', file: 'risks', description: 'Налоговые, судебные и контрагентские риски' },
    rating: { key: 'rating', title: 'Кредитный рейтинг', menuTitle: 'Рейтинг', file: 'rating', description: 'Предварительная банковская оценка клиента' },
    flight: { key: 'flight', title: 'Флот и налёт', menuTitle: 'Флот', file: 'flight', description: 'Налёт и покрытие кредитных и лизинговых платежей' }
  }
};

function doGet(e) {
  const pageKey = normalizePageKey_(e && e.parameter ? e.parameter.page : '');
  const page = APP_CONFIG.pages[pageKey];
  const params = e && e.parameter ? e.parameter : {};
  const template = HtmlService.createTemplateFromFile('template');
  template.pageKey = page.key;
  template.pageTitle = page.title;
  template.pageDescription = page.description;
  template.contentFile = page.file;
  template.navItems = getNavigationItems_();
  template.appConfig = { spreadsheetName: APP_CONFIG.spreadsheetName };
  template.appUrl = getScriptUrl();
  template.availableYears = getReportingYears_();
  const requestedYear = Number(params.year);
  const defaultYear = template.availableYears.length
    ? template.availableYears[template.availableYears.length - 1]
    : 2024;
  template.initialPeriod = {
    periodType: String(params.periodType || '').toLowerCase() === 'quarter' ? 'quarter' : 'year',
    year: template.availableYears.indexOf(requestedYear) !== -1 ? requestedYear : defaultYear,
    quarter: Math.max(1, Math.min(4, Number(params.quarter) || 1))
  };
  return template.evaluate()
    .setTitle(page.title + ' - Финансовое состояние авиакомпании')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function include(fileName) {
  return HtmlService.createHtmlOutputFromFile(String(fileName || '').trim()).getContent();
}

function getScriptUrl() { return ScriptApp.getService().getUrl(); }

/** Возвращает только годы подтверждённой годовой отчётности. */
function getReportingYears_() {
  const fallback = [2022, 2023, 2024];
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss && ss.getSheetByName('Плоская_таблица');
    if (!sheet || sheet.getLastRow() < 2) return fallback;
    const values = sheet.getDataRange().getValues();
    const headers = values[0].map(function(value) { return String(value || '').trim(); });
    const codeIndex = headers.indexOf('metric_code');
    const periodEndIndex = headers.indexOf('period_end');
    const periodTypeIndex = headers.indexOf('period_type');
    if (codeIndex < 0 || periodEndIndex < 0) return fallback;
    const years = values.slice(1).reduce(function(result, row) {
      const code = String(row[codeIndex] || '').trim();
      const periodType = periodTypeIndex >= 0 ? String(row[periodTypeIndex] || '').toLowerCase() : '';
      const match = String(row[periodEndIndex] || '').match(/(20\d{2})/);
      const year = match ? Number(match[1]) : 0;
      if (code === 'REVENUE' && year && (!periodType || periodType.indexOf('год') !== -1)) result[year] = true;
      return result;
    }, {});
    const result = Object.keys(years).map(Number).sort(function(a, b) { return a - b; });
    return result.length ? result : fallback;
  } catch (error) {
    return fallback;
  }
}

function getPageUrl(pageKey) {
  const key = normalizePageKey_(pageKey);
  return getScriptUrl() + '?page=' + encodeURIComponent(key);
}

function getAppShellState() {
  return { ok: true, data: { spreadsheetName: APP_CONFIG.spreadsheetName, pages: getNavigationItems_() }, warnings: [], updatedAt: new Date().toISOString() };
}

function normalizePageKey_(pageKey) {
  const key = String(pageKey || APP_CONFIG.defaultPage).trim().toLowerCase();
  return APP_CONFIG.pages[key] ? key : APP_CONFIG.defaultPage;
}

function getNavigationItems_() {
  return Object.keys(APP_CONFIG.pages).map(function(key) {
    const page = APP_CONFIG.pages[key];
    return { key: page.key, title: page.menuTitle, fullTitle: page.title, url: getPageUrl(page.key) };
  });
}
