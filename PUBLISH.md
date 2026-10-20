# Как выложить Booktify на GitHub

Репозиторий `9leywin/booktify` создан и связан с локальной папкой. Ниже — как
отправить новую версию и оформить релиз.

## Что уже готово

- коммит с изменениями версии и тег `v1.0.1`;
- файлы для релиза в `release\`:
  - `Booktify-1.0.1-setup.exe` (61,6 МБ)
  - `Booktify-1.0.1-portable-win64.zip` (33 МБ)
  - `SHA256SUMS.txt`

## Отправить код и тег

```powershell
cd C:\Users\artur\OneDrive\Documents\deepseek-harness\default-workspace\book-translator
git push origin main
git push origin v1.0.1
```

Проверить, что тег ушёл:

```powershell
git ls-remote --tags origin
```

## Оформить релиз

1. GitHub → репозиторий `booktify` → **Releases** → **Draft a new release**.
2. **Choose a tag** → `v1.0.1` → заголовок `Booktify 1.0.1`.
3. Описание (можно скопировать):

   ```
   - Версия приложения в правом нижнем углу окна.
   - Только DeepSeek, OpenAI и OpenRouter.
   - Ключ проверяется при вставке, список моделей загружается автоматически.
   - «Показать в папке» открывает папку с готовой книгой.
   ```

4. Прикрепи два файла из `release\` и `SHA256SUMS.txt`.
5. **Publish release**.

## Собрать новую версию

```powershell
powershell -File make-release.ps1 -Python "C:\utilities\bin\python.exe" -Version 1.0.2
```

Скрипт соберёт приложение и установщик, положит файлы в `release\` и пересчитает
контрольные суммы.

## Обновления в будущем

```powershell
git add .
git commit -m "что изменилось"
git tag -a v1.0.2 -m "Booktify 1.0.2"
git push origin main
git push origin v1.0.2
```

Затем — новый черновик релиза и два файла из `release\`.
