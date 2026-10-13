-- The home screen now shows balance and stock itself; drop the trailing hint from the default welcome texts.
UPDATE settings SET value = 'أهلاً بك في متجر مزارع Hay Day'
 WHERE key = 'welcome_text' AND value = 'أهلاً بك في متجر مزارع Hay Day
اختر من القائمة بالأسفل.';
UPDATE settings SET value = regexp_replace(value, '\s*اختر من القائمة بالأسفل\.?\s*$', '')
 WHERE key = 'welcome_text';
UPDATE settings SET value = regexp_replace(value, '\s*Choose from the menu below\.?\s*$', '')
 WHERE key = 'welcome_text_en';
