# Notion-flavored Markdown 요약

전문은 `notion-fetch`에 `id: "notion://docs/enhanced-markdown-spec"`을 넣어 읽는다. 아래는 글 작성에 실제로 필요한 부분만 추린 것이다.

## 기본

- 들여쓰기는 탭. 스페이스로 들여쓰면 계층이 깨진다.
- 이스케이프 대상: `\ * ~ ` $ [ ] < > { } | ^` (본문에서만. 코드 블록 안은 그대로).
- 빈 줄은 제거된다. 의도적인 빈 줄은 `<empty-block/>`.
- 블록 색: 줄 끝에 `{color="gray"}` 또는 `{color="blue_bg"}`.

## 인라인

| 표현 | 문법 |
|---|---|
| 굵게 | `**텍스트**` |
| 기울임 | `*텍스트*` |
| 취소선 | `~~텍스트~~` |
| 밑줄 | `<span underline="true">텍스트</span>` |
| 코드 | `` `코드` `` (줄바꿈은 `<br>`) |
| 링크 | `[텍스트](URL)` |
| 색 | `<span color="red">텍스트</span>` |
| 수식 | `` $`E=mc^2`$ `` |
| 줄바꿈(블록 내) | `<br>` |

색 이름: gray, brown, orange, yellow, green, blue, purple, pink, red. 배경은 `_bg` 접미(예: `yellow_bg`).

## 블록

```
# 제목1
## 제목2
### 제목3
- 글머리
	- 하위(탭)
1. 번호
- [ ] 할 일
- [x] 완료
> 인용<br>둘째 줄
---
<table_of_contents/>
```

### 표

```
<table header-row="true" fit-page-width="true">
	<tr>
		<td>헤더1</td>
		<td>헤더2</td>
	</tr>
	<tr>
		<td>값</td>
		<td>**굵게 가능**</td>
	</tr>
</table>
```

- 셀은 리치 텍스트만. 목록, 제목, 이미지 불가.
- `header-column="true"`로 첫 열을 헤더로 만들 수 있다.
- 셀 병합은 API로 불가. 필요하면 사용자가 UI에서 한다.

### 콜아웃

```
<callout icon="📌" color="gray_bg">
	첫 줄
	- 하위 블록도 가능
</callout>
```

`icon`은 생략 가능. 사용자가 이모지를 싫어하면 생략한다.

### 토글

```
<details>
<summary>제목</summary>
내용
</details>
```

토글 제목:

```
## 제목 {toggle="true"}
	자식 블록(탭 들여쓰기 필수)
```

### 컬럼과 탭

```
<columns>
	<column ratio="50">
		내용
	</column>
	<column ratio="50">
		내용
	</column>
</columns>
```

```
<tabs>
	<tab>
		탭 제목
		내용
	</tab>
</tabs>
```

### 코드와 다이어그램

````
```python
print("이스케이프하지 않는다")
```

```mermaid
flowchart LR
    A["입력 (파일)"] --> B["처리"]
```
````

Mermaid 노드 텍스트에 괄호나 특수문자가 있으면 큰따옴표로 감싼다.

### 언급

```
<mention-page url="https://www.notion.so/...">페이지 제목</mention-page>
<mention-user url="...">이름</mention-user>
<mention-date start="2026-09-04"/>
```

`<page url="...">`는 언급이 아니라 "하위 페이지로 이동"이다. 기존 페이지를 가리킬 때는 반드시 `mention-page`를 쓴다.

### 파일과 미디어

```
![캡션](이미지 URL)
<file src="URL">캡션</file>
<pdf src="URL">캡션</pdf>
<video src="URL">캡션</video>
```

## update-page 명령 요약

| command | 필수 인자 | 용도 |
|---|---|---|
| `insert_content` | `content`, `position` (`{"type":"start"}` 또는 `{"type":"end"}`) | 앞뒤에 덧붙이기 |
| `update_content` | `content_updates: [{old_str, new_str, replace_all_matches?}]` | 부분 교체. `old_str`은 fetch 결과와 정확히 일치해야 하고 유일해야 한다 |
| `replace_content` | `new_str` | 전체 교체. 하위 페이지가 있으면 `allow_deleting_content: true` 없이는 실패 |
| `update_properties` | `properties` | 제목이나 DB 속성 변경 |

`allow_async: false`를 주면 완료 후 응답한다. 바로 fetch로 확인할 때 필요하다.

## create-pages 요약

```json
{
  "creation_mode": "draft",
  "pages": [
    {
      "properties": {"title": "제목"},
      "content": "본문(제목은 넣지 않는다)"
    }
  ]
}
```

- 목적지를 지정받았으면 `creation_mode`를 빼고 `parent: {"page_id": "..."}`를 준다.
- 데이터베이스에 넣을 때는 먼저 DB URL을 fetch해 `collection://` 데이터 소스 ID와 속성 스키마를 확인하고 `parent: {"data_source_id": "..."}`를 쓴다.
