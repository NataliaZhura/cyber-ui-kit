/**
 * Единый источник данных для страниц дашборда.
 * Источник: лист "Плоская_таблица".
 * Расчётные показатели уже подготовлены в этой таблице как отдельные metric_code.
 */

const FLAT_SOURCE_SHEET = 'Плоская_таблица';

function flatReadRows_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('Активная Google-таблица недоступна.');
  const sheet = ss.getSheetByName(FLAT_SOURCE_SHEET);
  if (!sheet) throw new Error('Не найден лист "' + FLAT_SOURCE_SHEET + '".');
  const values = sheet.getDataRange().getValues();
  if (!values || values.length < 2) return [];
  const headers = values[0].map(function(h) { return String(h || '').trim(); });
  return values.slice(1).filter(function(row) {
    return row.some(function(cell) { return cell !== '' && cell !== null && cell !== undefined; });
  }).map(function(row) {
    const item = {};
    headers.forEach(function(header, index) { if (header) item[header] = row[index]; });
    return item;
  });
}

function flatToNumber_(value) {
  if (typeof value === 'number' && isFinite(value)) return value;
  if (value === null || value === undefined || value === '') return null;
  const normalized = String(value).replace(/\s/g, '').replace(',', '.');
  const number = Number(normalized);
  return isFinite(number) ? number : null;
}

function flatDate_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) return value;
  if (!value) return null;
  const text = String(value).trim();
  let match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  match = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (match) return new Date(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
  return null;
}

function flatYear_(value) {
  const date = flatDate_(value);
  return date ? date.getFullYear() : null;
}

function flatLatestYear_(rows) {
  return rows.reduce(function(maxYear, row) {
    const year = flatYear_(row.period_end);
    return year && year > maxYear ? year : maxYear;
  }, 0);
}

/** Годы, по которым есть годовая выручка из фактической отчетности. */
function flatReportingYears_(rows) {
  const result = {};
  (rows || []).forEach(function(row) {
    const code = String(row.metric_code || '').trim();
    const periodType = String(row.period_type || '').toLowerCase();
    const year = flatYear_(row.period_end);
    if (code === 'REVENUE' && year && (!periodType || periodType.indexOf('год') !== -1)) result[year] = true;
  });
  return Object.keys(result).map(Number).sort(function(a, b) { return a - b; });
}

function flatRowsByCode_(rows, code) {
  return rows.filter(function(row) { return String(row.metric_code || '').trim() === code; });
}

function flatMetricRow_(rows, code, year) {
  const candidates = flatRowsByCode_(rows, code);
  const exact = year ? candidates.filter(function(row) { return flatYear_(row.period_end) === year; }) : [];
  const pool = exact.length ? exact : candidates;
  if (!pool.length) return null;
  return pool.slice().sort(function(a, b) {
    return (flatDate_(b.period_end) || new Date(0)) - (flatDate_(a.period_end) || new Date(0));
  })[0];
}

function flatMetric_(rows, code, year) {
  const row = flatMetricRow_(rows, code, year);
  if (!row) return null;
  const numeric = flatToNumber_(row.value_numeric);
  return numeric !== null ? numeric : (row.value_display || null);
}

function flatLastMetric_(rows, code) {
  const candidates = flatRowsByCode_(rows, code);
  if (!candidates.length) return null;
  const row = candidates[candidates.length - 1];
  return flatToNumber_(row.value_numeric);
}

function flatText_(rows, code, year) {
  const row = flatMetricRow_(rows, code, year);
  if (!row) return '-';
  return row.value_display !== '' && row.value_display !== null && row.value_display !== undefined
    ? String(row.value_display)
    : (row.value_numeric === '' || row.value_numeric === null ? '-' : String(row.value_numeric));
}

function flatFormatNumber_(value, decimals) {
  if (value === null || value === undefined || value === '' || !isFinite(Number(value))) return '-';
  const fixed = Number(value).toFixed(decimals === undefined ? 0 : decimals);
  const parts = fixed.split('.');
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return parts.join(',');
}

function flatFormatPercent_(value) {
  return value === null || value === undefined ? '-' : flatFormatNumber_(Number(value) * 100, 1) + '%';
}

function flatFormatRatio_(value) {
  return value === null || value === undefined ? '-' : flatFormatNumber_(Number(value), 2) + 'x';
}

function flatBuildCompany_(rows) {
  return {
    name: String((rows[0] && rows[0].company_name) || 'АО «ЮТЭЙР-Вертолетные услуги»'),
    inn: flatText_(rows, 'COMPANY_INN'),
    city: flatText_(rows, 'COMPANY_CITY'),
    foundingDate: flatText_(rows, 'COMPANY_FOUNDING_DATE'),
    okved: flatText_(rows, 'COMPANY_OKVED'),
    director: flatText_(rows, 'COMPANY_DIRECTOR'),
    kpp: flatText_(rows, 'COMPANY_KPP'),
    ogrn: flatText_(rows, 'COMPANY_OGRN'),
    address: flatText_(rows, 'COMPANY_ADDRESS'),
    status: flatText_(rows, 'COMPANY_STATUS'),
    riskPercent: flatMetric_(rows, 'SITE_RISK_PERCENT'),
    riskText: flatText_(rows, 'SITE_RISK_TEXT')
  };
}

function flatBuildDashboardData_(year, periodType, quarter) {
  const rows = flatReadRows_();
  const reportingYears = flatReportingYears_(rows);
  const requestedYear = Number(year);
  const defaultYear = reportingYears.length ? reportingYears[reportingYears.length - 1] : flatLatestYear_(rows);
  const latestYear = reportingYears.indexOf(requestedYear) !== -1 ? requestedYear : defaultYear;
  const selectedPeriodType = String(periodType || 'year').toLowerCase() === 'quarter' ? 'quarter' : 'year';
  const selectedQuarter = Number(quarter) >= 1 && Number(quarter) <= 4 ? Number(quarter) : null;
  const selectedRows = selectedPeriodType === 'quarter' && selectedQuarter
    ? rows.filter(function(row) {
        const date = flatDate_(row.period_end);
        const rowType = String(row.period_type || '').toLowerCase();
        return date && flatYear_(row.period_end) === latestYear && Math.floor(date.getMonth() / 3) + 1 === selectedQuarter && rowType.indexOf('кварт') >= 0;
      })
    : rows;
  const valueRows = selectedPeriodType === 'quarter' ? selectedRows : rows;
  const value = function(code) { return flatMetric_(valueRows, code, selectedPeriodType === 'quarter' ? latestYear : latestYear); };
  const display = function(code) { return flatText_(valueRows, code, selectedPeriodType === 'quarter' ? latestYear : latestYear); };
  const fixedAssetsValue = flatToNumber_(value('FIXED_ASSETS'));
  const ebitValue = flatToNumber_(value('EBIT'));
  const depreciationValue = fixedAssetsValue === null ? null : fixedAssetsValue * 0.03;
  const ebitdaValue = ebitValue === null || depreciationValue === null ? null : ebitValue + depreciationValue;
  const liabilitiesValue = flatToNumber_(value('TOTAL_LIABILITIES'));
  const annualPaymentValue = flatToNumber_(value('ANNUAL_PAYMENT_TOTAL'));
  const debtEbitdaValue = liabilitiesValue !== null && ebitdaValue !== null && ebitdaValue > 0 ? liabilitiesValue / ebitdaValue : null;
  const dcrEbitdaValue = annualPaymentValue !== null && annualPaymentValue !== 0 && ebitdaValue !== null ? ebitdaValue / annualPaymentValue : null;
  const equityValue = flatToNumber_(value('EQUITY'));
  const assetsValue = flatToNumber_(value('ASSETS'));
  const equityShareValue = assetsValue !== null && assetsValue !== 0 && equityValue !== null ? equityValue / assetsValue : null;
  const officialDcrValue = flatToNumber_(flatMetric_(rows, 'OFFICIAL_DCR', latestYear));
  const ratingCriteria = [
    { code: 'NET_PROFIT', label: 'Чистая прибыль', value: flatToNumber_(value('NET_PROFIT')), max: 20, points: flatToNumber_(value('NET_PROFIT')) !== null && flatToNumber_(value('NET_PROFIT')) > 0 ? 20 : 0, status: flatToNumber_(value('NET_PROFIT')) !== null && flatToNumber_(value('NET_PROFIT')) > 0 ? 'положительная' : 'убыток' },
    { code: 'EQUITY_SHARE', label: 'Доля собственного капитала', value: equityShareValue, max: 20, points: equityShareValue !== null && equityShareValue >= 0.2 ? 20 : (equityShareValue !== null && equityShareValue >= 0.1 ? 10 : 0), status: equityShareValue !== null && equityShareValue >= 0.2 ? 'устойчивая' : 'низкая' },
    { code: 'EBITDA', label: 'EBITDA', value: ebitdaValue, max: 20, points: ebitdaValue !== null && ebitdaValue > 0 ? 20 : 0, status: ebitdaValue !== null && ebitdaValue > 0 ? 'положительная, оценочная' : 'не рассчитана' },
    { code: 'OFFICIAL_DCR', label: 'Официальный DCR', value: officialDcrValue, max: 25, points: officialDcrValue !== null && officialDcrValue >= 1.2 ? 25 : (officialDcrValue !== null && officialDcrValue >= 1 ? 15 : 0), status: officialDcrValue === null ? 'CFADS не подтвержден' : (officialDcrValue >= 1 ? 'покрытие есть' : 'покрытия нет') },
    { code: 'DEBT_EBITDA', label: 'Обязательства / EBITDA', value: debtEbitdaValue, max: 15, points: debtEbitdaValue !== null && debtEbitdaValue <= 3 ? 15 : (debtEbitdaValue !== null && debtEbitdaValue <= 6 ? 10 : (debtEbitdaValue !== null && debtEbitdaValue <= 10 ? 5 : 0)), status: debtEbitdaValue === null ? 'нет подтвержденной EBITDA' : (debtEbitdaValue <= 6 ? 'приемлемая нагрузка' : 'критическая нагрузка') }
  ];
  const ratingScore = ratingCriteria.reduce(function(sum, item) { return sum + item.points; }, 0);
  const ratingGrade = ratingScore >= 80 ? 'A' : (ratingScore >= 60 ? 'B' : (ratingScore >= 40 ? 'C' : 'D'));
  const riskYear = latestYear || 2024;
  const riskFacts = [
    { code: 'TAX_RISKS', label: 'Налоговые риски', value: flatText_(rows, 'TAX_RISKS', riskYear), status: 'подтверждено отчетностью' },
    { code: 'COURT_RISKS', label: 'Судебные риски', value: flatText_(rows, 'COURT_RISKS', riskYear), status: 'подтверждено отчетностью' },
    { code: 'BANKRUPTCY_RISK', label: 'Банкротство', value: flatText_(rows, 'BANKRUPTCY_RISK', riskYear), status: 'подтверждено отчетностью' },
    { code: 'COUNTERPARTY_LINKS', label: 'Связанные компании', value: flatText_(rows, 'COUNTERPARTY_LINKS', riskYear), status: 'подтверждено отчетностью' },
    { code: 'SANCTIONS_115FZ', label: '115-ФЗ', value: flatText_(rows, 'SANCTIONS_115FZ', riskYear), status: 'подтверждено отчетностью' },
    { code: 'COURT_PLAINTIFF', label: 'Истец в судах, дел', value: flatText_(rows, 'COURT_PLAINTIFF_' + riskYear, riskYear), status: 'числовая выгрузка' },
    { code: 'COURT_DEFENDANT', label: 'Ответчик в судах, дел', value: flatText_(rows, 'COURT_DEFENDANT_' + riskYear, riskYear), status: 'числовая выгрузка' },
    { code: 'ENFORCEMENT_OPEN', label: 'Открытые исполнительные производства', value: flatText_(rows, 'ENFORCEMENT_OPEN_' + riskYear, riskYear), status: 'числовая выгрузка' },
    { code: 'ENFORCEMENT_EXECUTED', label: 'Исполненные производства', value: flatText_(rows, 'ENFORCEMENT_EXECUTED_' + riskYear, riskYear), status: 'числовая выгрузка' },
    { code: 'COURT_DEFENDANT_CLAIMS', label: 'Сумма исков в роли ответчика', value: flatText_(rows, 'COURT_DEFENDANT_CLAIMS_' + riskYear, riskYear), status: 'тыс. руб. по выгрузке' },
    { code: 'COURT_PLAINTIFF_CLAIMS', label: 'Сумма исков в роли истца', value: flatText_(rows, 'COURT_PLAINTIFF_CLAIMS_' + riskYear, riskYear), status: 'тыс. руб. по выгрузке' },
    { code: 'ACCOUNT_BLOCKS_COUNT', label: 'Блокировки счетов', value: flatText_(rows, 'ACCOUNT_BLOCKS_COUNT'), status: 'внешняя проверка' },
    { code: 'PLEDGE_MEASURES_COUNT', label: 'Залоговые меры', value: flatText_(rows, 'PLEDGE_MEASURES_COUNT'), status: 'внешняя проверка' },
    { code: 'PLEDGED_PROPERTY_TEXT', label: 'Заложенное имущество', value: flatText_(rows, 'PLEDGED_PROPERTY_TEXT'), status: 'внешняя проверка' },
    { code: 'GOV_CONTRACTS_FLAG', label: 'Госконтракты', value: flatText_(rows, 'GOV_CONTRACTS_FLAG'), status: 'внешняя проверка' },
    { code: 'MASS_FOUNDER_FLAG', label: 'Массовый учредитель', value: flatText_(rows, 'MASS_FOUNDER_FLAG'), status: 'внешняя проверка' },
    { code: 'MASS_MANAGER_FLAG', label: 'Массовый руководитель', value: flatText_(rows, 'MASS_MANAGER_FLAG'), status: 'внешняя проверка' },
    { code: 'DISQUALIFICATION_FLAG', label: 'Дисквалификация руководителей', value: flatText_(rows, 'DISQUALIFICATION_FLAG'), status: 'внешняя проверка' },
    { code: 'SUSPICIOUS_OPERATIONS_RISK', label: 'Риск подозрительных операций', value: flatText_(rows, 'SUSPICIOUS_OPERATIONS_RISK'), status: 'внешняя проверка' }
  ];
  return {
    company: flatBuildCompany_(rows),
    year: latestYear,
    periodType: selectedPeriodType,
    quarter: selectedQuarter,
    periodAvailable: selectedPeriodType === 'year' || selectedRows.length > 0,
    sourceSheet: FLAT_SOURCE_SHEET,
    kpis: {
      revenue: value('REVENUE'), revenueFormatted: display('REVENUE'),
      netProfit: value('NET_PROFIT'), netProfitFormatted: display('NET_PROFIT'),
      fixedAssets: fixedAssetsValue, fixedAssetsFormatted: flatFormatNumber_(fixedAssetsValue),
      depreciation: depreciationValue, depreciationFormatted: flatFormatNumber_(depreciationValue),
      ebit: ebitValue, ebitFormatted: flatFormatNumber_(ebitValue),
      assets: value('ASSETS'), assetsFormatted: display('ASSETS'),
      liabilities: value('TOTAL_LIABILITIES'), liabilitiesFormatted: display('TOTAL_LIABILITIES'),
      longTermLiabilities: value('LONG_TERM_LIABILITIES'), longTermLiabilitiesFormatted: display('LONG_TERM_LIABILITIES'),
      shortTermLiabilities: value('SHORT_TERM_LIABILITIES'), shortTermLiabilitiesFormatted: display('SHORT_TERM_LIABILITIES'),
      equity: value('EQUITY'), equityFormatted: display('EQUITY'),
      netAssets: value('NET_ASSETS'), netAssetsFormatted: display('NET_ASSETS'),
      cash: value('CASH'), cashFormatted: display('CASH'),
      creditDebt: value('CREDIT_DEBT'), creditDebtFormatted: display('CREDIT_DEBT'),
      netDebt: liabilitiesValue !== null && flatToNumber_(value('CASH')) !== null ? liabilitiesValue - flatToNumber_(value('CASH')) : null,
      netDebtFormatted: liabilitiesValue !== null && flatToNumber_(value('CASH')) !== null ? flatFormatNumber_(liabilitiesValue - flatToNumber_(value('CASH'))) : '-',
      ebitda: ebitdaValue, ebitdaFormatted: flatFormatNumber_(ebitdaValue),
      ebit: ebitValue, ebitFormatted: flatFormatNumber_(ebitValue),
      netMargin: value('NET_MARGIN'), netMarginFormatted: flatFormatPercent_(value('NET_MARGIN')),
      ebitMargin: value('EBIT_MARGIN'), ebitMarginFormatted: flatFormatPercent_(value('EBIT_MARGIN')),
      ebitdaMargin: ebitdaValue !== null && flatToNumber_(value('REVENUE')) ? ebitdaValue / flatToNumber_(value('REVENUE')) : null, ebitdaMarginFormatted: ebitdaValue !== null && flatToNumber_(value('REVENUE')) ? flatFormatPercent_(ebitdaValue / flatToNumber_(value('REVENUE'))) : '-',
      debtEbitda: debtEbitdaValue, debtEbitdaFormatted: flatFormatRatio_(debtEbitdaValue),
      officialCfads: flatText_(rows, 'OFFICIAL_CFADS', latestYear),
      modelFcf: value('MODEL_FCF'), modelFcfFormatted: display('MODEL_FCF'),
      officialDcr: flatText_(rows, 'OFFICIAL_DCR', latestYear),
      dcrEbitda: dcrEbitdaValue, dcrEbitdaFormatted: flatFormatRatio_(dcrEbitdaValue),
      dcrFcf: value('DCR_FCF_PROXY'), dcrFcfFormatted: display('DCR_FCF_PROXY'),
      leaseCoverage: value('LEASE_COVERAGE_FCF'), leaseCoverageFormatted: display('LEASE_COVERAGE_FCF'),
      annualPayment: value('ANNUAL_PAYMENT_TOTAL'), annualPaymentFormatted: display('ANNUAL_PAYMENT_TOTAL'),
      leasePayment: value('LEASE_PAYMENT'), leasePaymentFormatted: display('LEASE_PAYMENT'),
      newLeaseCapacity: value('NEW_LEASE_CAPACITY'), newLeaseCapacityFormatted: display('NEW_LEASE_CAPACITY')
    },
    rating: { grade: ratingGrade, score: ratingScore, maxScore: 100, criteria: ratingCriteria },
    riskFacts: riskFacts,
    flightEconomics: {
      flightHours: value('ANNUAL_FLEET_HOURS'), hourRate: value('TARIFF_PER_HOUR_MODEL'), hourCost: value('COST_PER_HOUR_MODEL'), hourMargin: value('MARGIN_PER_HOUR_MODEL'),
      annualFlightRevenue: (flatToNumber_(value('ANNUAL_FLEET_HOURS')) || 0) * (flatToNumber_(value('TARIFF_PER_HOUR_MODEL')) || 0),
      annualPayment: annualPaymentValue, leasePayment: flatToNumber_(value('LEASE_PAYMENT')), creditCoverage: value('FLIGHT_COVERAGE_CREDIT'), leaseCoverage: value('FLIGHT_COVERAGE_LEASE'),
      femFlightHours: flatMetric_(rows, 'FEM_MI8_FLIGHT_HOURS', latestYear), femHourRateScenario1: flatMetric_(rows, 'FEM_MI8_HOUR_RATE_SCENARIO_1', latestYear), femHourRateScenario2: flatMetric_(rows, 'FEM_MI8_HOUR_RATE_SCENARIO_2', latestYear), femLeasePaymentAnnual: flatMetric_(rows, 'FEM_MI8_LEASE_PAYMENT_ANNUAL', latestYear)
    },
    history: [2022, 2023, 2024].map(function(itemYear) {
      const historyFixedAssets = flatToNumber_(flatMetric_(rows, 'FIXED_ASSETS', itemYear));
      const historyEbit = flatToNumber_(flatMetric_(rows, 'EBIT', itemYear));
      const historyDepreciation = historyFixedAssets === null ? null : historyFixedAssets * 0.03;
      const historyEbitda = historyEbit === null || historyDepreciation === null ? null : historyEbit + historyDepreciation;
      return {
        year: itemYear,
        revenue: flatMetric_(rows, 'REVENUE', itemYear) || 0,
        ebit: flatMetric_(rows, 'EBIT', itemYear) || 0,
        depreciation: (flatToNumber_(flatMetric_(rows, 'FIXED_ASSETS', itemYear)) || 0) * 0.03,
        netProfit: flatMetric_(rows, 'NET_PROFIT', itemYear) || 0,
        ebitda: historyEbitda === null ? 0 : historyEbitda,
        assets: flatMetric_(rows, 'ASSETS', itemYear) || 0,
        liabilities: flatMetric_(rows, 'TOTAL_LIABILITIES', itemYear) || 0,
        equity: flatMetric_(rows, 'EQUITY', itemYear) || 0,
        receivables: flatMetric_(rows, 'AR', itemYear) || 0,
        payables: flatMetric_(rows, 'AP', itemYear) || 0
      };
    }),
    ratios: {
      ebitMargin: value('EBIT_MARGIN'), netMargin: value('NET_MARGIN'), ebitdaMargin: value('EBITDA_MARGIN_PROXY'),
      arTurnover: value('AR_TURNOVER'), arDays: value('AR_DAYS'), apTurnover: value('AP_TURNOVER'), apDays: value('AP_DAYS'),
      inventoryTurnover: value('INV_TURNOVER'), inventoryDays: value('INV_DAYS')
    },
    fleet: {
      mi8: value('FLEET_MI8'), avgHours: value('AVG_FLIGHT_HOURS'), annualHours: value('ANNUAL_FLEET_HOURS'),
      tariff: value('TARIFF_PER_HOUR_MODEL'), cost: value('COST_PER_HOUR_MODEL'), margin: value('MARGIN_PER_HOUR_MODEL'),
      creditCoverage: value('FLIGHT_COVERAGE_CREDIT'), leaseCoverage: value('FLIGHT_COVERAGE_LEASE')
    },
    risks: {
      tax: flatText_(rows, 'TAX_RISKS'), court: flatText_(rows, 'COURT_RISKS'), counterparties: flatText_(rows, 'COUNTERPARTY_LINKS'),
      bankruptcy: flatText_(rows, 'BANKRUPTCY_RISK'), sanctions: flatText_(rows, 'SANCTIONS_115FZ')
    },
    warnings: (selectedPeriodType === 'quarter' && selectedRows.length === 0 ? ['Квартальные строки отсутствуют в листе «Плоская_таблица». Показаны прочерки до загрузки квартальных данных.'] : []).concat([
      'Официальные CFADS и DCR отсутствуют в исходных данных.',
      'EBITDA, FCF и DCR proxy являются модельными расчётами.',
      'Подробные налоговые, судебные и контрагентские блоки 1cont ограничены текущим доступом.'
    ]),
    updatedAt: new Date().toISOString()
  };
}

function getFlatDashboardData(params) {
  try {
    const requestedYear = Number(params && params.year);
    const periodType = params && params.periodType ? params.periodType : 'year';
    const quarter = Number(params && params.quarter) || null;
    return prepareResponse(createSuccessResponse(flatBuildDashboardDataV2_(requestedYear || null, periodType, quarter)));
  } catch (error) {
    return prepareResponse(createErrorResponse(error));
  }
}

/**
 * Возвращает значение только за указанный год. В отличие от старой функции,
 * не подменяет отсутствующий исторический год последним доступным значением.
 */
function flatMetricExact_(rows, code, year) {
  const candidates = flatRowsByCode_(rows, code).filter(function(row) {
    return !year || flatYear_(row.period_end) === year;
  });
  if (!candidates.length) return null;
  const row = candidates.slice().sort(function(a, b) {
    return (flatDate_(b.period_end) || new Date(0)) - (flatDate_(a.period_end) || new Date(0));
  })[0];
  return flatToNumber_(row.value_numeric);
}

/**
 * Возвращает значение строго за выбранный квартал.
 * Годовые строки никогда не подставляются вместо квартальных.
 */
function flatMetricQuarterExact_(rows, code, year, quarter) {
  const candidates = flatRowsByCode_(rows, code).filter(function(row) {
    const date = flatDate_(row.period_end);
    return date && date.getFullYear() === year &&
      Math.floor(date.getMonth() / 3) + 1 === quarter &&
      String(row.period_type || '').toLowerCase().indexOf('кварт') >= 0;
  });
  if (!candidates.length) return null;
  const row = candidates.slice().sort(function(a, b) {
    return (flatDate_(b.period_end) || new Date(0)) - (flatDate_(a.period_end) || new Date(0));
  })[0];
  return flatToNumber_(row.value_numeric);
}

function flatFormatMillions_(value, decimals) {
  const number = flatToNumber_(value);
  return number === null ? '-' : flatFormatNumber_(number / 1000, decimals === undefined ? 1 : decimals);
}

function flatQuarterMetricHistory_(rows, code, year) {
  return rows.filter(function(row) {
    const date = flatDate_(row.period_end);
    return String(row.metric_code || '') === code && date && date.getFullYear() === year &&
      String(row.period_type || '').toLowerCase().indexOf('кварт') >= 0;
  }).sort(function(a, b) {
    return (flatDate_(a.period_end) || new Date(0)) - (flatDate_(b.period_end) || new Date(0));
  }).map(function(row) {
    const date = flatDate_(row.period_end);
    return {
      quarter: 'К' + (Math.floor(date.getMonth() / 3) + 1),
      value: flatToNumber_(row.value_numeric)
    };
  }).filter(function(row) { return row.value !== null; });
}

/**
 * Единая модель данных для дашборда.
 * В источнике денежные строки хранятся в тыс. руб., на экране они выводятся
 * в млн руб. Значения ставки и налёта не масштабируются.
 */
function flatBuildDashboardDataV2_(year, periodType, quarter) {
  const base = flatBuildDashboardData_(year, periodType, quarter);
  const rows = flatReadRows_();
  const selectedYear = base.year;
  const isQuarter = base.periodType === 'quarter';
  const quarterAvailable = !isQuarter || base.periodAvailable;
  const metric = function(code) {
    if (!quarterAvailable) return null;
    return isQuarter
      ? flatMetricQuarterExact_(rows, code, selectedYear, base.quarter)
      : flatMetricExact_(rows, code, selectedYear);
  };
  const money = function(code) { return flatFormatMillions_(metric(code)); };
  const revenue = metric('REVENUE');
  const ebit = metric('EBIT');
  const netProfit = metric('NET_PROFIT');
  const fixedAssets = metric('FIXED_ASSETS');
  const depreciation = fixedAssets === null ? null : fixedAssets * 0.03;
  const ebitda = ebit === null || depreciation === null ? null : ebit + depreciation;
  const assets = metric('ASSETS');
  const liabilities = metric('TOTAL_LIABILITIES');
  const equity = metric('EQUITY');
  const cash = metric('CASH');
  const creditDebt = metric('CREDIT_DEBT');
  const leaseDebt = metric('LEASE_DEBT_OUTSTANDING');
  const grossDebtConfirmed = creditDebt === null ? null : creditDebt + (leaseDebt === null ? 0 : leaseDebt);
  const grossDebtIncomplete = leaseDebt === null;
  const annualPayment = metric('ANNUAL_PAYMENT_TOTAL');
  const leasePayment = metric('LEASE_PAYMENT');
  const modelFcf = metric('MODEL_FCF');
  const policyDebtEbitda = flatMetricExact_(rows, 'POLICY_MAX_DEBT_EBITDA', selectedYear) || 3;
  const policyBufferMonths = flatMetricExact_(rows, 'POLICY_LIQUIDITY_BUFFER_MONTHS', selectedYear) || 3;
  const creditDebtEbitda = creditDebt !== null && ebitda !== null && ebitda > 0 ? creditDebt / ebitda : null;
  const headroomByDebt = creditDebt !== null && ebitda !== null ? Math.max(0, policyDebtEbitda * ebitda - creditDebt) : null;
  const monthlyMandatoryPayment = annualPayment === null ? null : annualPayment / 12;
  const permanentLiquidityBuffer = monthlyMandatoryPayment === null ? null : monthlyMandatoryPayment * policyBufferMonths;
  const liquidityDeficit = permanentLiquidityBuffer === null || cash === null ? null : Math.max(0, permanentLiquidityBuffer - cash);
  const cashRunwayMonths = monthlyMandatoryPayment === null || monthlyMandatoryPayment === 0 || cash === null ? null : cash / monthlyMandatoryPayment;
  const workingCapitalProxy = cash === null ? null : cash + (metric('AR') || 0) + (metric('INVENTORY') || 0) - (metric('AP') || 0);
  const equityShare = assets && equity !== null ? equity / assets : null;
  const liabilitiesShare = assets && liabilities !== null ? liabilities / assets : null;
  const totalLiabilitiesEbitda = liabilities !== null && ebitda !== null && ebitda > 0 ? liabilities / ebitda : null;

  const historyYears = isQuarter ? [] : [2022, 2023, 2024].filter(function(itemYear) {
    return selectedYear < 2022 ? false : (selectedYear <= 2024 ? itemYear <= selectedYear : true);
  });
  const history = historyYears.map(function(itemYear) {
    const itemRevenue = flatMetricExact_(rows, 'REVENUE', itemYear);
    const itemProfit = flatMetricExact_(rows, 'NET_PROFIT', itemYear);
    const itemEbit = flatMetricExact_(rows, 'EBIT', itemYear);
    const itemFixedAssets = flatMetricExact_(rows, 'FIXED_ASSETS', itemYear);
    const itemDepreciation = itemFixedAssets === null ? null : itemFixedAssets * 0.03;
    const itemEquity = flatMetricExact_(rows, 'EQUITY', itemYear);
    return {
      year: itemYear,
      revenue: itemRevenue,
      revenueMln: itemRevenue === null ? null : itemRevenue / 1000,
      netProfit: itemProfit,
      netProfitMln: itemProfit === null ? null : itemProfit / 1000,
      ebit: itemEbit,
      depreciation: itemDepreciation,
      ebitda: itemEbit === null || itemDepreciation === null ? null : itemEbit + itemDepreciation,
      netMargin: itemRevenue && itemProfit !== null ? itemProfit / itemRevenue : null,
      roe: itemEquity && itemProfit !== null ? itemProfit / itemEquity : null,
      selected: itemYear === selectedYear
    };
  });
  let fcfQuarterly = flatQuarterMetricHistory_(rows, 'MODEL_FCF', selectedYear).map(function(row) {
    return { quarter: row.quarter, value: row.value, valueMln: row.value / 1000, modeled: false };
  });
  const projectMetric = function(code, itemYear) {
    return flatMetricExact_(rows, code, itemYear);
  };
  const projectYear = selectedYear >= 2026 && selectedYear <= 2040 ? selectedYear : 2026;
  const projectModel = {
    displayYear: projectYear,
    available: projectMetric('PROJECT_REVENUE', projectYear) !== null,
    helicopterCost: projectMetric('PROJECT_HELICOPTER_COST', 2026),
    leaseRate: projectMetric('PROJECT_LEASE_RATE', 2026),
    leaseTermYears: projectMetric('PROJECT_LEASE_TERM_YEARS', 2026),
    wacc: projectMetric('PROJECT_WACC', 2026),
    npv: projectMetric('PROJECT_NPV', 2026),
    minDscr: projectMetric('PROJECT_MIN_DSCR', 2026),
    dscrCovenant: projectMetric('PROJECT_DSCR_COVENANT', 2026),
    hourlyRate: projectMetric('PROJECT_HOURLY_RATE', projectYear),
    annualHours: projectMetric('PROJECT_FLIGHT_HOURS_ANNUAL', projectYear),
    revenue: projectMetric('PROJECT_REVENUE', projectYear),
    opex: projectMetric('PROJECT_TOTAL_OPEX', projectYear),
    ebitda: projectMetric('PROJECT_EBITDA', projectYear),
    ebitdaMargin: projectMetric('PROJECT_EBITDA_MARGIN', projectYear),
    leasePayment: projectMetric('PROJECT_LEASE_PAYMENT', projectYear),
    interest: projectMetric('PROJECT_INTEREST', projectYear),
    principal: projectMetric('PROJECT_PRINCIPAL_REPAYMENT', projectYear),
    fcf: projectMetric('PROJECT_FCF', projectYear),
    netProfit: projectMetric('PROJECT_NET_PROFIT', projectYear),
    dscr: projectMetric('PROJECT_DSCR', projectYear),
    openingBalance: projectMetric('PROJECT_LEASE_BALANCE_OPENING', projectYear),
    closingBalance: projectMetric('PROJECT_LEASE_BALANCE_CLOSING', projectYear),
    factMonthlyHours2025: projectMetric('FNB_AVG_FLIGHT_HOURS_MONTHLY', 2025),
    factHourlyRate2025: projectMetric('FNB_HOURLY_RATE', 2025),
    factHourlyCost2025: projectMetric('FNB_HOURLY_COST_EX_LEASE', 2025),
    factAnnualPayment2025: projectMetric('FNB_CURRENT_LEASE_PAYMENT_ANNUAL', 2025)
  };
  const projectHistory = [];
  for (var projectHistoryYear = 2026; projectHistoryYear <= 2040; projectHistoryYear++) {
    const projectRevenue = projectMetric('PROJECT_REVENUE', projectHistoryYear);
    if (projectRevenue === null) continue;
    projectHistory.push({
      year: projectHistoryYear,
      revenue: projectRevenue,
      ebitda: projectMetric('PROJECT_EBITDA', projectHistoryYear),
      fcf: projectMetric('PROJECT_FCF', projectHistoryYear),
      netProfit: projectMetric('PROJECT_NET_PROFIT', projectHistoryYear),
      dscr: projectMetric('PROJECT_DSCR', projectHistoryYear),
      leasePayment: projectMetric('PROJECT_LEASE_PAYMENT', projectHistoryYear),
      closingBalance: projectMetric('PROJECT_LEASE_BALANCE_CLOSING', projectHistoryYear)
    });
  }

  // Факт компании хранится до 2024 года. С 2026 года период выбирает
  // соответствующий год прогнозной финансовой модели новой сделки.
  const isProjectForecast = selectedYear >= 2026 && selectedYear <= 2040 && projectModel.available;
  const projectPeriodShare = isProjectForecast && isQuarter ? 0.25 : 1;
  const cumulativeProjectFcf = isProjectForecast ? projectHistory.filter(function(item) {
    return item.year <= selectedYear && item.fcf !== null;
  }).reduce(function(sum, item) {
    return sum + item.fcf * (item.year === selectedYear ? (isQuarter ? (base.quarter * 0.25) : 1) : 1);
  }, 0) : null;
  const shownRevenue = isProjectForecast ? projectModel.revenue * projectPeriodShare : revenue;
  const shownEbitda = isProjectForecast ? projectModel.ebitda * projectPeriodShare : ebitda;
  const shownNetProfit = isProjectForecast ? projectModel.netProfit * projectPeriodShare : netProfit;
  const shownAnnualPayment = isProjectForecast ? projectModel.leasePayment * projectPeriodShare : annualPayment;
  const shownFcf = isProjectForecast ? projectModel.fcf * projectPeriodShare : modelFcf;
  if (isProjectForecast && isQuarter && !fcfQuarterly.length) {
    fcfQuarterly = [1, 2, 3, 4].map(function(itemQuarter) {
      return { quarter: 'К' + itemQuarter, value: projectModel.fcf * 0.25, valueMln: projectModel.fcf / 4000, modeled: true };
    });
  }

  base.kpis = {
    revenue: shownRevenue, revenueFormatted: flatFormatMillions_(shownRevenue),
    netProfit: shownNetProfit, netProfitFormatted: flatFormatMillions_(shownNetProfit),
    ebit: ebit, ebitFormatted: flatFormatMillions_(ebit),
    fixedAssets: fixedAssets, fixedAssetsFormatted: flatFormatMillions_(fixedAssets),
    depreciation: depreciation, depreciationFormatted: flatFormatMillions_(depreciation),
    ebitda: shownEbitda, ebitdaFormatted: flatFormatMillions_(shownEbitda),
    assets: isProjectForecast ? null : assets, assetsFormatted: flatFormatMillions_(isProjectForecast ? null : assets),
    liabilities: isProjectForecast ? null : liabilities, liabilitiesFormatted: flatFormatMillions_(isProjectForecast ? null : liabilities),
    liabilitiesShare: liabilitiesShare, liabilitiesShareFormatted: flatFormatPercent_(liabilitiesShare),
    totalLiabilitiesEbitda: totalLiabilitiesEbitda, totalLiabilitiesEbitdaFormatted: flatFormatRatio_(totalLiabilitiesEbitda),
    longTermLiabilities: metric('LONG_TERM_LIABILITIES'), longTermLiabilitiesFormatted: money('LONG_TERM_LIABILITIES'),
    shortTermLiabilities: metric('SHORT_TERM_LIABILITIES'), shortTermLiabilitiesFormatted: money('SHORT_TERM_LIABILITIES'),
    equity: isProjectForecast ? null : equity, equityFormatted: flatFormatMillions_(isProjectForecast ? null : equity),
    netAssets: metric('NET_ASSETS'), netAssetsFormatted: money('NET_ASSETS'),
    cash: isProjectForecast ? null : cash, cashFormatted: flatFormatMillions_(isProjectForecast ? null : cash),
    creditDebt: isProjectForecast ? null : creditDebt, creditDebtFormatted: flatFormatMillions_(isProjectForecast ? null : creditDebt),
    leaseDebt: leaseDebt, leaseDebtFormatted: flatFormatMillions_(leaseDebt),
    grossDebt: grossDebtConfirmed, grossDebtFormatted: flatFormatMillions_(grossDebtConfirmed), grossDebtIncomplete: grossDebtIncomplete,
    netDebt: grossDebtConfirmed === null || cash === null ? null : grossDebtConfirmed - cash,
    netDebtFormatted: grossDebtConfirmed === null || cash === null ? '-' : flatFormatMillions_(grossDebtConfirmed - cash),
    netMargin: shownRevenue && shownNetProfit !== null ? shownNetProfit / shownRevenue : null, netMarginFormatted: shownRevenue && shownNetProfit !== null ? flatFormatPercent_(shownNetProfit / shownRevenue) : '-',
    ebitMargin: revenue && ebit !== null ? ebit / revenue : null, ebitMarginFormatted: revenue && ebit !== null ? flatFormatPercent_(ebit / revenue) : '-',
    ebitdaMargin: revenue && ebitda !== null ? ebitda / revenue : null, ebitdaMarginFormatted: revenue && ebitda !== null ? flatFormatPercent_(ebitda / revenue) : '-',
    roe: equity && netProfit !== null ? netProfit / equity : null, roeFormatted: equity && netProfit !== null ? flatFormatPercent_(netProfit / equity) : '-',
    equityShare: equityShare, equityShareFormatted: flatFormatPercent_(equityShare),
    dso: metric('AR_DAYS'), dsoFormatted: flatFormatNumber_(metric('AR_DAYS'), 1),
    dpo: metric('AP_DAYS'), dpoFormatted: flatFormatNumber_(metric('AP_DAYS'), 1),
    dio: metric('INV_DAYS'), dioFormatted: flatFormatNumber_(metric('INV_DAYS'), 1),
    workingCapital: workingCapitalProxy, workingCapitalFormatted: flatFormatMillions_(workingCapitalProxy),
    creditDebtEbitda: creditDebtEbitda, creditDebtEbitdaFormatted: flatFormatRatio_(creditDebtEbitda),
    policyDebtEbitda: policyDebtEbitda, policyDebtEbitdaFormatted: flatFormatRatio_(policyDebtEbitda),
    preliminaryDebtHeadroom: headroomByDebt, preliminaryDebtHeadroomFormatted: flatFormatMillions_(headroomByDebt),
    annualPayment: shownAnnualPayment, annualPaymentFormatted: flatFormatMillions_(shownAnnualPayment),
    leasePayment: isProjectForecast ? projectModel.leasePayment : leasePayment, leasePaymentFormatted: flatFormatMillions_(isProjectForecast ? projectModel.leasePayment : leasePayment),
    modelFcf: shownFcf, modelFcfFormatted: flatFormatMillions_(shownFcf),
    cumulativeProjectFcf: cumulativeProjectFcf, cumulativeProjectFcfFormatted: flatFormatMillions_(cumulativeProjectFcf),
    officialCfads: '-', officialDcr: '-',
    monthlyMandatoryPayment: isProjectForecast && shownAnnualPayment !== null ? shownAnnualPayment / (isQuarter ? 3 : 12) : monthlyMandatoryPayment, monthlyMandatoryPaymentFormatted: flatFormatMillions_(isProjectForecast && shownAnnualPayment !== null ? shownAnnualPayment / (isQuarter ? 3 : 12) : monthlyMandatoryPayment),
    policyBufferMonths: policyBufferMonths,
    permanentLiquidityBuffer: permanentLiquidityBuffer, permanentLiquidityBufferFormatted: flatFormatMillions_(permanentLiquidityBuffer),
    liquidityDeficit: liquidityDeficit, liquidityDeficitFormatted: flatFormatMillions_(liquidityDeficit),
    cashRunwayMonths: cashRunwayMonths, cashRunwayMonthsFormatted: cashRunwayMonths === null ? '-' : flatFormatNumber_(cashRunwayMonths, 2),
    dcrFcf: shownAnnualPayment && shownFcf !== null ? shownFcf / shownAnnualPayment : null,
    dcrFcfFormatted: shownAnnualPayment && shownFcf !== null ? flatFormatRatio_(shownFcf / shownAnnualPayment) : '-',
    leaseCoverage: (isProjectForecast ? projectModel.leasePayment : leasePayment) && shownFcf !== null ? shownFcf / (isProjectForecast ? projectModel.leasePayment : leasePayment) : null,
    leaseCoverageFormatted: (isProjectForecast ? projectModel.leasePayment : leasePayment) && shownFcf !== null ? flatFormatRatio_(shownFcf / (isProjectForecast ? projectModel.leasePayment : leasePayment)) : '-',
    newLeaseCapacity: null, newLeaseCapacityFormatted: 'н/д'
  };
  base.history = history;
  base.profitabilityHistory = history.map(function(row) { return { year: row.year, netMargin: row.netMargin, roe: row.roe }; });
  base.fcfQuarterly = fcfQuarterly;
  base.projectModel = projectModel;
  base.projectModel.periodShare = projectPeriodShare;
  base.projectModel.periodInterest = projectModel.interest === null ? null : projectModel.interest * projectPeriodShare;
  base.projectModel.periodPrincipal = projectModel.principal === null ? null : projectModel.principal * projectPeriodShare;
  base.projectModel.periodLeasePayment = projectModel.leasePayment === null ? null : projectModel.leasePayment * projectPeriodShare;
  base.projectModel.periodAllocationNote = isProjectForecast && isQuarter ? 'Квартальный прогноз: 25% годового значения. Исходная финансовая модель содержит годовые, а не квартальные строки.' : '';
  base.projectHistory = projectHistory;
  base.periodBasis = isProjectForecast ? 'forecast' : 'actual';
  base.periodAvailable = isProjectForecast || (isQuarter ? quarterAvailable : rows.some(function(row) {
    return flatYear_(row.period_end) === selectedYear;
  }));
  base.cashModelHistory = [2022, 2023, 2024].map(function(itemYear) {
    return {
      year: itemYear,
      cfo: flatMetricExact_(rows, 'MODEL_CFO_PROXY', itemYear),
      capex: flatMetricExact_(rows, 'MODEL_CAPEX_PROXY', itemYear),
      fcfAfterCapex: flatMetricExact_(rows, 'MODEL_FCF_CAPEX_PROXY', itemYear),
      fcfe: flatMetricExact_(rows, 'MODEL_FCFE_PROXY', itemYear),
      interest: flatMetricExact_(rows, 'MODEL_INTEREST_PAYABLE', itemYear)
    };
  });
  base.financialState = {
    label: netProfit !== null && netProfit < 0 || equityShare !== null && equityShare < 0.1 ? 'напряженное' : 'устойчивое',
    text: netProfit !== null && netProfit < 0
      ? 'В последнем доступном году получен чистый убыток при положительной расчётной EBITDA. Доля собственного капитала низкая.'
      : 'Финансовый результат положительный по доступной отчётности.',
    evidence: [
      'Чистая прибыль: ' + flatFormatMillions_(netProfit) + ' млн руб.',
      'EBITDA: ' + flatFormatMillions_(ebitda) + ' млн руб. (расчёт: EBIT + 3% основных средств).',
      'Доля собственного капитала: ' + flatFormatPercent_(equityShare) + '.',
      'Денежные средства: ' + flatFormatMillions_(cash) + ' млн руб.'
    ]
  };
  base.debtCapacity = {
    label: headroomByDebt === null ? 'н/д' : (headroomByDebt > 0 ? 'есть предварительный запас' : 'дополнительная нагрузка не рекомендуется'),
    text: grossDebtIncomplete
      ? 'Расчёт предварительный: остаток лизингового долга не загружен. Показан только лимит по подтверждённому кредитному долгу и расчётной EBITDA.'
      : 'Показан предварительный лимит по кредитному долгу и расчётной EBITDA.',
    headroom: headroomByDebt,
    headroomFormatted: flatFormatMillions_(headroomByDebt)
  };
  base.liquidity = {
    text: 'Постоянный буфер задан как ' + policyBufferMonths + ' месяца обязательных платежей. Это управленческое допущение, его можно изменить в плоской таблице.',
    bufferMonths: policyBufferMonths
  };
  const ratingCriteriaV2 = [
    { label: 'Финансовая устойчивость', value: equityShare, max: 25, points: equityShare !== null && equityShare >= 0.2 ? 25 : (equity !== null && equity > 0 ? 5 : 0), status: equityShare !== null && equityShare >= 0.2 ? 'достаточная доля капитала' : 'низкая доля собственного капитала' },
    { label: 'Покрытие обязательств', value: modelFcf, max: 30, points: modelFcf !== null && modelFcf > 0 ? 15 : 0, status: modelFcf !== null && modelFcf > 0 ? 'модельный FCF положительный' : 'модельный FCF отрицательный или не загружен' },
    { label: 'Ликвидность', value: cashRunwayMonths, max: 15, points: cashRunwayMonths !== null && cashRunwayMonths >= policyBufferMonths ? 15 : (cashRunwayMonths !== null && cashRunwayMonths >= 1 ? 5 : 0), status: cashRunwayMonths !== null && cashRunwayMonths >= policyBufferMonths ? 'буфер достаточен' : 'буфер ниже управленческого ориентира' },
    { label: 'Качество бизнеса', value: ebitda, max: 15, points: ebitda !== null && ebitda > 0 ? 10 : 0, status: ebitda !== null && ebitda > 0 ? 'расчётная EBITDA положительная' : 'EBITDA не подтверждена' },
    { label: 'Внешние риски', value: null, max: 15, points: 0, status: 'требуется периодическая сверка реестров и источников' }
  ];
  const ratingScoreV2 = ratingCriteriaV2.reduce(function(sum, item) { return sum + item.points; }, 0);
  base.rating = {
    grade: ratingScoreV2 >= 80 ? 'A' : (ratingScoreV2 >= 60 ? 'B' : (ratingScoreV2 >= 40 ? 'C' : 'D')),
    score: ratingScoreV2,
    maxScore: 100,
    criteria: ratingCriteriaV2
  };
  const financialCondition = netProfit !== null && netProfit < 0 ||
    equityShare !== null && equityShare < 0.1 ||
    modelFcf !== null && modelFcf < 0 ||
    totalLiabilitiesEbitda !== null && totalLiabilitiesEbitda > 10
    ? 'слабое'
    : 'устойчивое';
  base.executiveConclusion = {
    condition: financialCondition,
    rating: base.rating.grade,
    ratingScore: base.rating.score,
    headline: financialCondition === 'слабое'
      ? 'Компания финансово слабая: чистый убыток, низкая доля собственного капитала и отрицательный модельный свободный денежный поток ограничивают способность принимать новую нагрузку.'
      : 'Финансовое состояние компании по доступным данным устойчивое.',
    debtText: 'Обязательства составляют ' + flatFormatMillions_(liabilities) + ' млн руб. или ' + flatFormatPercent_(liabilitiesShare) + ' активов. Отношение всех обязательств к расчётной EBITDA: ' + flatFormatRatio_(totalLiabilitiesEbitda) + '.',
    turnoverText: 'DSO: ' + flatFormatNumber_(metric('AR_DAYS'), 1) + ' дня. DPO: ' + flatFormatNumber_(metric('AP_DAYS'), 1) + ' дня. DIO: ' + flatFormatNumber_(metric('INV_DAYS'), 1) + ' дня.',
    cashFlowText: modelFcf === null || annualPayment === null
      ? 'Недостаточно данных для оценки покрытия обязательных платежей свободным денежным потоком.'
      : modelFcf < 0
        ? 'Модельный свободный денежный поток отрицательный: ' + flatFormatMillions_(modelFcf) + ' млн руб. Он не покрывает годовой обязательный платёж ' + flatFormatMillions_(annualPayment) + ' млн руб.'
        : 'Модельный свободный денежный поток составляет ' + flatFormatMillions_(modelFcf) + ' млн руб. Покрытие годового обязательного платежа: ' + flatFormatRatio_(modelFcf / annualPayment) + '.'
  };
  if (isProjectForecast) {
    base.financialState = {
      label: 'прогноз финансовой модели',
      text: 'Показатели за ' + selectedYear + ' год относятся к новой лизинговой сделке по финансовой модели, а не к фактической отчетности компании.',
      evidence: [
        'Выручка проекта: ' + flatFormatMillions_(projectModel.revenue) + ' млн руб.',
        'EBITDA проекта: ' + flatFormatMillions_(projectModel.ebitda) + ' млн руб.',
        'FCF проекта за выбранный период: ' + flatFormatMillions_(shownFcf) + ' млн руб.',
        'Накопленный FCF с 2026 по ' + selectedYear + ' год: ' + flatFormatMillions_(cumulativeProjectFcf) + ' млн руб.'
      ]
    };
    base.debtCapacity = {
      label: 'прогноз новой сделки',
      text: 'Остаток долга и платежи относятся к новой лизинговой сделке. Это не прогноз всего баланса компании.',
      headroom: null,
      headroomFormatted: 'н/д'
    };
    base.rating = {
      grade: 'н/д',
      score: null,
      maxScore: 100,
      criteria: [
        { label: 'Режим данных', value: selectedYear, max: 0, points: 0, status: 'прогноз финансовой модели, не кредитный рейтинг компании' },
        { label: 'DSCR проекта', value: projectModel.dscr, max: 0, points: 0, status: 'EBITDA проекта / годовой лизинговый платеж' }
      ]
    };
    base.executiveConclusion = {
      condition: projectModel.fcf !== null && projectModel.fcf >= 0 && projectModel.dscr !== null && projectModel.dscr >= (projectModel.dscrCovenant || 1.2) ? 'приемлемый прогноз' : 'требует пересмотра условий',
      rating: 'н/д',
      ratingScore: null,
      headline: 'Прогноз новой лизинговой сделки на ' + selectedYear + ' год. Фактическая отчетность компании не подставляется вместо прогноза.',
      debtText: 'Годовой лизинговый платеж проекта: ' + flatFormatMillions_(projectModel.leasePayment) + ' млн руб. Остаток лизингового долга на конец года: ' + flatFormatMillions_(projectModel.closingBalance) + ' млн руб.',
      turnoverText: 'DSCR проекта: ' + flatFormatRatio_(projectModel.dscr) + '. В финансовой модели DSCR = EBITDA проекта / годовой лизинговый платеж.',
      cashFlowText: 'FCF проекта за выбранный период: ' + flatFormatMillions_(shownFcf) + ' млн руб. Накопленный FCF с 2026 по выбранный период: ' + flatFormatMillions_(cumulativeProjectFcf) + ' млн руб.'
    };
  }
  if (isQuarter && !quarterAvailable && !isProjectForecast) {
    base.executiveConclusion = {
      condition: 'нет данных',
      rating: 'н/д',
      ratingScore: null,
      headline: 'За выбранный квартал нет строк в листе «Плоская_таблица». Годовые показатели не подставлены вместо квартальных.',
      debtText: 'Загрузите квартальные значения показателей, которые нужны для оценки обязательств и лимита новой нагрузки.',
      turnoverText: 'Загрузите квартальные значения дебиторской и кредиторской задолженности или их оборачиваемости.',
      cashFlowText: 'Загрузите квартальный свободный денежный поток и обязательные платежи.'
    };
  }
  base.warnings = [
    'Все денежные показатели на экране показаны в млн руб. Исходные значения в плоской таблице хранятся в тыс. руб.',
    projectModel.available ? 'Новая сделка Ми-8МТВ-1 показана отдельно как прогноз финансовой модели с 2026 года. Она не заменяет фактическую отчетность компании.' : '',
    grossDebtIncomplete ? 'Не загружен остаток лизингового долга. Лимит по новой нагрузке нельзя считать окончательным.' : '',
    fcfQuarterly.length ? '' : 'Квартальный FCF не загружен. Третий график появится после загрузки финансовой модели по кварталам.'
  ].filter(function(item) { return item; });
  return base;
}

function flatPeriodMeta_(data) {
  const isQuarter = data.periodType === 'quarter';
  const quarter = data.quarter || 1;
  const startMonth = isQuarter ? (quarter - 1) * 3 + 1 : 1;
  const endMonth = isQuarter ? quarter * 3 : 12;
  const endDay = new Date(data.year, endMonth, 0).getDate();
  function pad(value) { return String(value).padStart(2, '0'); }
  return {
    periodType: data.periodType,
    year: data.year,
    quarter: data.quarter,
    startDate: data.year + '-' + pad(startMonth) + '-01',
    endDate: data.year + '-' + pad(endMonth) + '-' + pad(endDay),
    periodAvailable: data.periodAvailable
  };
}

function flatCapitalApi(params) {
  const result = getFlatDashboardData(params);
  if (result.status !== 'success') return result;
  const data = result.data;
  const history = data.history || [];
  return prepareResponse(createSuccessResponse({
    kpis: {
      equity: data.kpis.equity, equityFormatted: data.kpis.equityFormatted,
      currentRatio: null, financialIndependence: data.kpis.equity && data.kpis.assets ? data.kpis.equity / data.kpis.assets : null,
      snapshotDateDisplay: String(data.year)
    },
    charts: {
      assetsStructure: [{ label: 'Активы', value: data.kpis.assets || 0 }],
      passivesStructure: [{ label: 'Собственный капитал', value: data.kpis.equity || 0 }, { label: 'Обязательства', value: data.kpis.liabilities || 0 }],
      receivablesDynamics: history.map(function(row) { return { dateDisplay: String(row.year), amount: row.receivables }; }),
      payablesDynamics: history.map(function(row) { return { dateDisplay: String(row.year), amount: row.payables }; }),
      equityDebtStructure: history.map(function(row) {
        const total = row.equity + row.liabilities;
        return { dateDisplay: String(row.year), equityShare: total ? row.equity / total : 0, liabilitiesShare: total ? row.liabilities / total : 0 };
      }),
      ratiosDynamics: history.map(function(row) {
        const total = row.equity + row.liabilities;
        return { dateDisplay: String(row.year), currentRatio: null, financialIndependence: total ? row.equity / (row.assets || total) : 0 };
      })
    },
    meta: { module: 'capital', sourceSheet: FLAT_SOURCE_SHEET, snapshotDateDisplay: String(data.year), period: flatPeriodMeta_(data) },
    flat: data
  }));
}

function flatMoneyApi(params) {
  const result = getFlatDashboardData(params);
  if (result.status !== 'success') return result;
  const data = result.data;
  return prepareResponse(createSuccessResponse({
    kpis: {
      income: null, expense: null, netCashFlow: data.kpis.modelFcf, netCashFlowFormatted: data.kpis.modelFcfFormatted,
      operatingNetFlow: null, investingNetFlow: null, financingNetFlow: null,
      officialCfads: data.kpis.officialCfads, modelFcf: data.kpis.modelFcf, modelFcfFormatted: data.kpis.modelFcfFormatted,
      annualPayment: data.kpis.annualPayment, annualPaymentFormatted: data.kpis.annualPaymentFormatted,
      leasePayment: data.kpis.leasePayment, leasePaymentFormatted: data.kpis.leasePaymentFormatted,
      officialDcr: data.kpis.officialDcr, dcrFcf: data.kpis.dcrFcf, dcrFcfFormatted: data.kpis.dcrFcfFormatted,
      leaseCoverage: data.kpis.leaseCoverage, leaseCoverageFormatted: data.kpis.leaseCoverageFormatted,
      newLeaseCapacity: data.kpis.newLeaseCapacity, newLeaseCapacityFormatted: data.kpis.newLeaseCapacityFormatted
    },
    filters: { accounts: [], counterparties: [], articles: [], directions: [], minDate: data.year + '-01-01', maxDate: data.year + '-12-31' },
    tables: { oddsReport: [] }, charts: { suppliers: [], buyers: [], directions: [], monthlyNetFlow: [], monthlyBalances: [], expenseStructure: [] },
    meta: { module: 'money', sourceSheet: FLAT_SOURCE_SHEET, rowsTotal: 0, rowsFiltered: 0, rowsUsed: 0, period: flatPeriodMeta_(data) }, flat: data
  }));
}

function flatProfitApi(params) {
  const result = getFlatDashboardData(params);
  if (result.status !== 'success') return result;
  const data = result.data;
  const rows = data.history;
  const cogs = flatLastMetric_(flatReadRows_(), 'COGS');
  const revenue = data.kpis.revenue;
  const cogsShare = revenue ? cogs / revenue : null;
  return prepareResponse(createSuccessResponse({
    kpis: {
      revenue: data.kpis.revenue, revenueFormatted: data.kpis.revenueFormatted,
      cogs: cogs, cogsFormatted: flatFormatNumber_(cogs), cogsShare: cogsShare, grossMargin: cogsShare === null ? null : 1 - cogsShare,
      fixedCostsShare: null, netProfit: data.kpis.netProfit, netProfitFormatted: data.kpis.netProfitFormatted, netProfitMargin: data.ratios.netMargin
    },
    filters: { projects: [], directions: [], articles: [], sections: [], minDate: '2022-01-01', maxDate: data.year + '-12-31' },
    tables: { constructionProjects: [], repairProjects: [] },
    charts: {
      revenueAndGrossMargin: rows.map(function(row) { return { monthLabel: String(row.year), revenue: row.revenue, grossMargin: null }; }),
      revenueByDirection: { rows: [], directions: [] }, grossProfitByDirection: { rows: [], directions: [] },
      netProfitAndMargin: rows.map(function(row) { return { monthLabel: String(row.year), netProfit: row.netProfit, margin: null }; })
    },
    meta: { module: 'profit', sourceSheet: FLAT_SOURCE_SHEET, period: flatPeriodMeta_(data) }, flat: data
  }));
}
