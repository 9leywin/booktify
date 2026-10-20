# Как выложить Booktify на GitHub

Сборки и репозиторий готовы. Осталось создать репозиторий и загрузить файлы —
это делается один раз, дальше обновления уходят одной командой.

## Что уже готово

- `release\Booktify-1.0.1-setup.exe` — установщик (61,6 МБ)
- `release\Booktify-1.0.1-portable-win64.zip` — portable-версия (33 МБ)
- `release\SHA256SUMS.txt` — контрольные суммы
- README, LICENSE (MIT), CHANGELOG, `.gitignore`
- `.github/workflows/build.yml` — CI собирает обе версии на тег `v*`

## Шаг 1. Поставить Git

```powershell
winget install --id Git.Git -e --source winget
```

После установки закрой и открой PowerShell заново. Проверка: `git --version`.

## Шаг 2. Создать репозиторий на GitHub

На сайте GitHub: **New repository** → имя `booktify` → **Public** или **Private** →
**не** добавляй README, .gitignore и лицензию (они уже есть) → **Create repository**.

## Шаг 3. Залить код

В папке проекта:

```powershell
cd C:\Users\artur\OneDrive\Documents\deepseek-harness\default-workspace\book-translator
git init -b main
git add .
git commit -m "Booktify 1.0.1"
git remote add origin https://github.com/ТВОЙ_ЛОГИН/booktify.git
git push -u origin main
```

При первом push Git попросит войти в GitHub — откроется браузер, это нормально.

Проверить, что тяжёлые папки не попали в коммит:

```powershell
git status --short
```

В списке не должно быть `dist`, `release`, `build`, `tests/_work`.

## Шаг 4. Выложить сборки как релиз

1. На GitHub открой **Releases** → **Draft a new release**.
2. Tag: `v1.0.1`, заголовок: `Booktify 1.0.1`.
3. Прикрепи два файла из папки `release`:
   - `Booktify-1.0.1-setup.exe`
   - `Booktify-1.0.1-portable-win64.zip`
4. **Publish release**.

После этого CI (`.github/workflows/build.yml`) на каждый новый тег будет сам
собирать обе версии и прикреплять их к релизу.

## Обновления в будущем

```powershell
git add .
git commit -m "что изменилось"
git tag v1.0.1
git push
git push --tags
```

Тег `v1.0.1` запустит сборку и создаст релиз автоматически.

## Если Git ставить не хочется

Можно обойтись GitHub Desktop: **Add local repository** → выбрать папку проекта →
**Publish repository**. Сборки всё равно прикрепляются вручную в разделе Releases,
потому что они слишком большие для обычного коммита (33 и 61 МБ при лимите 100 МБ
на файл — технически можно, но захламляет историю).
