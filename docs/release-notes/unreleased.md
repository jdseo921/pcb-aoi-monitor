# Unreleased / 미출시 (draft, needs native review)

Release notes follow the Engineering standard ("Release notes"): one template, English and Korean together,
a requirement or bug ID on every item, and the first section is never skipped. At release time this file is
renamed to `<version>.md` and a new `unreleased.md` starts empty.

> Korean text in this file is a draft, machine-assisted, and needs review by a native speaker who knows SMT
> terms before it reaches a customer (Customers & Launch, "Both languages").

## Changes that can alter verdicts / 판정에 영향을 줄 수 있는 변경 (draft)

None. / 없음.

## New / 신규 (draft)

- [REQ-LOG-004] The app writes a JSON-lines log in the workspace's logs folder, one file per day (UTC), with time, level, module, event, record ids and the app version; it never holds images or personal data beyond a user's UUID (#4, part). / 앱이 작업 폴더의 logs 폴더에 하루(UTC) 한 파일씩 JSON 라인 로그를 기록합니다. 시각, 수준, 모듈, 이벤트, 기록 ID, 앱 버전을 담고 이미지나 사용자 UUID 외의 개인 정보는 담지 않습니다 (#4, 일부).
- [REQ-LOG-004] An append-only audit trail records who changed what and when, with the record before and after and a reason; the database refuses any change or deletion of an entry. Recipe saves are the first entries; the other writes are wired in S16 (#4, part). / 누가 무엇을 언제 바꿨는지를 변경 전후 기록과 사유와 함께 남기는 추가 전용 감사 기록이 생겼습니다. 데이터베이스가 항목의 수정과 삭제를 거부합니다. 레시피 저장이 첫 항목이며 나머지 쓰기는 S16에서 연결됩니다 (#4, 일부).

- [REQ-INSP-006] The Inspection page's alarm log shows the ISO date, 24-hour local time, level, AOI-<AREA>-<NNN> code and message of every alarm (an NG verdict, a missing AI model, every error shown), and the last 1,000 alarms survive a restart (#4, part). / 검사 페이지의 알람 목록이 모든 알람(NG 판정, AI 모델 없음, 표시된 모든 오류)의 ISO 날짜, 24시간 현지 시각, 수준, AOI-<영역>-<번호> 코드, 메시지를 보여주며, 최근 1,000개의 알람은 재시작 후에도 남습니다 (#4, 일부).
- [REQ-LOG-005] An unhandled error no longer takes the app down with a stack trace: it is logged with the build version and the trace, stored as an alarm, and shown as a plain message with its code, what happened and what to do; the app reopens on the page it was on (#4, part). / 처리되지 않은 오류가 더 이상 스택 추적과 함께 앱을 종료시키지 않습니다. 빌드 버전과 추적 정보가 로그에 기록되고 알람으로 저장되며, 코드와 무슨 일이 있었는지, 어떻게 해야 하는지를 담은 안내 메시지로 표시됩니다. 앱은 마지막에 열려 있던 페이지에서 다시 시작합니다 (#4, 일부).
- [REQ-SET-019] Every error dialog shows an AOI-<AREA>-<NNN> code, what happened and what to do; stack traces and raw exception text go only to the log (#4). / 모든 오류 대화 상자가 AOI-<영역>-<번호> 코드와 무슨 일이 있었는지, 어떻게 해야 하는지를 보여주며, 스택 추적과 예외 원문은 로그에만 기록됩니다 (#4).

## Improved / 개선 (draft)

- [REQ-USR-001] Every write in the service layer checks the signed-in role and refuses with AOI-USR-001 when it is too low (Engineer for training data, models, recipes, tests, exports and archiving; Admin for users), so no screen can bypass the rule (#11, part). / 서비스 계층의 모든 쓰기가 로그인한 역할을 확인하고 역할이 낮으면 AOI-USR-001로 거부합니다(학습 데이터, 모델, 레시피, 테스트, 내보내기, 보관은 Engineer, 사용자는 Admin). 어떤 화면도 이 규칙을 우회할 수 없습니다 (#11, 일부).
- [REQ-LOG-004] Every write is audited with the values before and after: board models, reference images, samples, training, model activation and rollback, recipes, test runs, exports, archiving and user changes. / 모든 쓰기가 변경 전후 값과 함께 감사 기록에 남습니다: 보드 모델, 기준 이미지, 샘플, 학습, 모델 활성화와 롤백, 레시피, 테스트 실행, 내보내기, 보관, 사용자 변경.
- [REQ-USR-001] Screens read and change data only through AppContext's typed calls: no page runs SQL, reaches the database or builds the inspection engine itself, and a layer test keeps it that way. Nothing visible changes (#11, part). / 화면이 데이터를 읽고 바꿀 때 AppContext의 형식이 지정된 호출만 사용합니다. 어떤 페이지도 SQL을 실행하거나 데이터베이스에 직접 접근하거나 검사 엔진을 직접 만들지 않으며, 계층 테스트가 이를 지킵니다. 눈에 보이는 변화는 없습니다 (#11, 일부).
- [REQ-SET-021] Background work (inspection runs, training, batch tests) goes through one job pool owned by the service layer, with progress, cancel and finished callbacks and no Qt in it, so the same jobs can run without a screen; a job's signals always arrive on the UI thread. Nothing visible changes (#11, part). / 백그라운드 작업(검사 실행, 학습, 일괄 테스트)이 서비스 계층이 소유한 하나의 작업 풀을 통해 실행됩니다. 진행률, 취소, 완료 콜백을 제공하고 Qt에 의존하지 않아 같은 작업을 화면 없이도 실행할 수 있으며, 작업의 신호는 항상 UI 스레드에서 도착합니다. 눈에 보이는 변화는 없습니다 (#11, 일부).
- [REQ-LOG-004] Errors from the engine and data layer carry a code AOI-<AREA>-<NNN> from one catalogue ([docs/error-codes.md](../error-codes.md)) and say what happened and what to do (#4, part). / 엔진과 데이터 계층의 오류에 하나의 목록([docs/error-codes.md](../error-codes.md))에서 가져온 AOI-<영역>-<번호> 코드가 붙고, 무슨 일이 있었는지와 어떻게 해야 하는지를 알려줍니다 (#4, 일부).
- [REQ-INSP-007] The golden-board comparison step is rewritten for speed: about 20 times faster at 5 MP and 12 times at 0.3 MP on a 4-core test VM (not the reference PC), with identical difference maps, masks and regions and the same verdicts on the synthetic regression set (#12). / 골든 보드 비교 단계를 더 빠르게 다시 작성했습니다: 4코어 테스트 VM(기준 PC 아님)에서 5 MP 기준 약 20배, 0.3 MP 기준 약 12배 빠르며, 합성 회귀 세트에서 차이 지도, 마스크, 영역과 판정이 동일합니다 (#12).

## Fixed / 수정 (draft)

- [REQ-SET-016] The database is created and changed only through numbered migrations recorded in the workspace, and it runs in write-ahead-log mode with a full sync on every commit, so a finished write survives a power cut (#2, part). / 데이터베이스는 작업 폴더에 기록되는 번호 매긴 마이그레이션으로만 생성·변경되며, 매 커밋마다 완전 동기화하는 WAL 모드로 동작하여 완료된 기록이 전원 차단에도 남습니다 (#2, 일부).
- [REQ-SET-017] Inspections, AI models, recipes, samples and users carry a UUID beside their local number, and every time is stored in UTC with an offset and shown in local time (#2, part). / 검사, AI 모델, 레시피, 샘플, 사용자 기록에 로컬 번호와 함께 UUID가 붙고, 모든 시각은 오프셋이 있는 UTC로 저장되어 현지 시각으로 표시됩니다 (#2, 일부).
- [REQ-SET-001] Image, overlay and AI model paths are stored relative to the workspace, so a workspace folder can be moved or restored from a backup and every image, model and result still opens (#2). / 이미지, 오버레이, AI 모델 경로를 작업 폴더 기준 상대 경로로 저장하므로 작업 폴더를 옮기거나 백업에서 복원해도 모든 이미지, 모델, 결과가 열립니다 (#2).
- [REQ-INSP-008] Every file the app writes is written whole or not at all (temporary file, flush, atomic rename), and an inspection's record and its defects are saved in one transaction, so a crash or power cut leaves no half-written result; 20 process kills in the test suite lost no finished result (#2). / 앱이 쓰는 모든 파일은 전체가 기록되거나 전혀 기록되지 않으며(임시 파일, 플러시, 원자적 이름 변경), 검사 기록과 결함은 한 트랜잭션으로 저장되므로 충돌이나 전원 차단 시 반쯤 기록된 결과가 남지 않습니다. 테스트에서 20회 프로세스 강제 종료 후 완료된 결과가 하나도 사라지지 않았습니다 (#2).

## Security / 보안 (draft)

- [REQ-TRN-014] AI model files load as weights only on PyTorch 2.6 or later; a file that needs code to load is refused with an error naming the file (#1). / AI 모델 파일은 PyTorch 2.6 이상에서 가중치 전용으로만 불러오며, 코드 실행이 필요한 파일은 파일명을 알리는 오류와 함께 거부됩니다 (#1).

## Known issues / 알려진 문제 (draft)

- [REQ-USR-002] Until sign-in ships at 1.0, the user is picked from a list without a password, so an audit entry records the picked name and proves nothing about who acted (ADR 0002). / 1.0에서 로그인이 제공되기 전까지 사용자는 비밀번호 없이 목록에서 선택되므로, 감사 기록은 선택된 이름만 남기며 누가 실제로 했는지는 증명하지 못합니다 (ADR 0002).

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-TRN-014] AI model files written by v0.1 no longer load; retrain after upgrading. v0.1 workspaces hold test data only and are not upgraded (ADR 0001). / v0.1이 만든 AI 모델 파일은 더 이상 불러올 수 없으므로 업그레이드 후 다시 학습합니다. v0.1 작업 폴더는 테스트 데이터만 담고 있으며 업그레이드되지 않습니다 (ADR 0001).
- [REQ-SET-016] A workspace created by v0.1 is refused at start-up with a message; choose a new workspace folder in Settings (ADR 0004). A workspace on a network drive is refused too. / v0.1이 만든 작업 폴더는 시작 시 안내 메시지와 함께 거부되므로 설정에서 새 작업 폴더를 선택합니다 (ADR 0004). 네트워크 드라이브의 작업 폴더도 거부됩니다.

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
