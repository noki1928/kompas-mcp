# Аудит исходного проекта (2026-10-01)

## Что уже работало

20 MCP-tools в `server.py`, MCP SDK 1.30 / stdio, один STA-поток в
`ComWorker`, единый экземпляр API5/API7 через `ksGetApplication7`.
`Kompas` содержит 2D-примитивы, документы, DXF и исполнение Python;
`Cad3DMixin` — замкнутые эскизы, выдавливание/вырез, основную метрику тела.
`capture.py` делает PrintWindow-снимок окна. 16 unit tests и два реальных
stdio smoke tests подтверждали базовое 2D/3D.

## Пробелы и риски

| Область | Исходное состояние | Необходимое изменение |
|---|---|---|
| API escape hatch | Только unsandboxed exec | Типизированные get/set/call/cast, TLB-describe, JSON handles |
| Ссылки | UUID для 3D, новые ID при каждом чтении | Единый реестр, scope документа, поколения топологии, очистка |
| Ошибки | Исключения превращаются SDK в текст | HRESULT, excepinfo, контекст, рекомендации, error envelope |
| Документы | create/open/SaveAs, только 3 типа | activate/close/save, остальные типы, защита changed |
| Состояние | Нет отдельного контроля ручных изменений | Снимок дерева/геометрии, compare token, conservative invalidation |
| Модель | Только sketch/extrusion и главное тело | Полное EntityCollection/Feature, тело/грани/рёбра, поиск |
| Параметры | Нет | Semantic get/set и общий доступ к definition |
| Эскизы | Атомарные rect/circle/polygon | Begin/edit/end и batch entities, лицо/плоскость |
| Операции | Extrude/cut only | Вращение, фаски/скругления, SDK discovery для прочих |
| Чертежи | Нет views/dimensions/reading | API7 контейнеры, ассоциативные виды, листы, dimensions |
| Export/vision | Window PNG thumbnail + DXF | native raster/PDF/STEP/STL, виды/камера, tiles |
| Сборки | Нет | Components/placement/tree; generic mates |
| Undo | Нет | Checkpoint копия с явно описанным restore |
| Logging | Нет журнала CAD-действий | JSONL на диске, без stdout, ограниченные payload |

## Наблюдения из живого КОМПАС v25

- `Document2D` — factory; активный документ получается через `ActiveDocument2D`.
- API5 cut direction противоположен boss direction; рабочий код уже это учитывает.
- Созданный feature не гарантирует изменение геометрии: проверка объёма обязательна.
- API5 `ksLDimParam` имеет `GetSPar/GetDPar/GetTPar`; ошибочные имена не использовать.
- В API7 контейнер `ISymbols2DContainer.LineDimensions`, не `LinearDimensions`.
- `IDimensionText.Height` опубликован в TLB, но отсутствует у данного runtime
  dispatch: необходимо проверять фактическую поддержку, не доверять только `dir`.
- Не менять/закрывать открытые пользовательские документы ради тестов.

## Порядок расширения

1. SDK catalog + diagnostics + registry + generic API.
2. Lifecycle/state/checkpoints/logging.
3. Tree/topology/features/sketch editing + операции.
4. Native export/camera/drawing/assembly + реальные smoke tests.
5. MCP-only end-to-end и документированная coverage с доказательствами.

Не считать опубликованный метод проверенной возможностью. В COVERAGE разделять
live-tested, доступный generic route и ещё не проверенные workflows.
