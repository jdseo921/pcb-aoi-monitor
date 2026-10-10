# Unreleased / 미출시 (draft, needs native review)

Release notes follow the Engineering standard ("Release notes"): one template, English and Korean together,
a requirement or bug ID on every item, and the first section is never skipped. At release time this file is
renamed to `<version>.md` and a new `unreleased.md` starts empty.

> Korean text in this file is a draft, machine-assisted, and needs review by a native speaker who knows SMT
> terms before it reaches a customer (Customers & Launch, "Both languages").

## Changes that can alter verdicts / 판정에 영향을 줄 수 있는 변경 (draft)

None. / 없음.

## New / 신규 (draft)

- [REQ-INSP-012] An Admin sets how long OK results' maps are kept and the largest image (megapixels and MB) on Settings; before, only in settings.json (#153). / 관리자가 설정 페이지에서 OK 결과 맵 보관 기간과 최대 이미지 크기(메가픽셀, MB)를 설정합니다. 이전에는 settings.json에서만 가능했습니다(#153).

## Improved / 개선 (draft)

- [REQ-SET-004] Text on the green, red and blue fills (verdict banner, Start, Stop, primary and danger buttons) is black, reading at 5.0:1 or more; it was white at 3.3 to 4.2:1 (#150). / 녹색, 빨간색, 파란색 배경 위 글자(판정 배너, 시작, 정지, 주요 및 위험 버튼)가 검은색이 되어 5.0:1 이상으로 읽힙니다. 이전에는 흰색으로 3.3~4.2:1이었습니다(#150).
- [REQ-INSP-002] Defect box labels on Inspection, Compare and AI Model Test, and in the saved overlay, carry the severity word and shape: "1 Polarity Error ◆ Critical", ■ Major, ● Minor (#152). / 검사, 비교, AI 모델 테스트 화면과 저장된 오버레이의 결함 상자 라벨에 심각도 단어와 모양이 표시됩니다: "1 Polarity Error ◆ Critical", ■ Major, ● Minor(#152).
- [REQ-INSP-016] Home's second step card reads "Train AI model" (was "Self-train") (#154). / 홈의 두 번째 단계 카드 이름이 "Train AI model"이 되었습니다(이전 "Self-train")(#154).

## Fixed / 수정 (draft)

None. / 없음.

## Security / 보안 (draft)

- [REQ-USR-001] Only an Admin exports customer results: Export CSV and Export Image Overlays on Logs & Export, Export CSV, Export Report and Validation Report… on AI Model Test, and Export Manifest… on Training are hidden for an Engineer and refused with AOI-USR-001 (#151). Save Image… (F9) stays with every role. / 고객 결과는 관리자만 내보낼 수 있습니다. 로그 및 내보내기, AI 모델 테스트, 학습 페이지의 내보내기 버튼은 엔지니어에게 숨겨지고 AOI-USR-001로 거부됩니다(#151). 이미지 저장(F9)은 모든 역할에 그대로 남습니다.

## Known issues / 알려진 문제 (draft)

None. / 없음.

## Upgrade notes / 업그레이드 안내 (draft)

- [REQ-USR-001] An Engineer who exported results before now asks an Admin to do it (#151). / 이전에 결과를 내보내던 엔지니어는 이제 관리자에게 요청해야 합니다(#151).

<!--
Item format: "- [REQ-INSP-005] Start, Stop, Next Board and Save Result work by F5, F6, F8 and F9. / F5, F6, F8, F9 키로
검사 시작, 정지, 다음 보드, 결과 저장을 할 수 있습니다." One line per item, English first, Korean after the slash,
the ID in brackets. A change that can alter a verdict goes in the first section with its before/after result on
the synthetic regression set and a note that customers re-validate before it goes live (Engineering, Change control).
-->
