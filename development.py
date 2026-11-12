import re


DEVELOPMENT_SCOPE = "accepting-development"

BUILD_WORK = re.compile(
    r"코딩\s*(?:대회|테스트|과제)|프로그래밍|알고리즘\s*(?:문제|대회|경진)|"
    r"데이터\s*(?:분석|시각화|사이언스|엔지니어링|경진)|"
    r"(?:AI|인공지능|머신러닝|딥러닝)\s*(?:에이전트|agent|모델)\s*(?:개발|구현|학습|훈련|평가|설계)|"
    r"(?:앱|어플리케이션|애플리케이션|소프트웨어|\bSW\b|웹\s*(?:사이트|서비스|앱)?|"
    r"게임|서비스|플랫폼|솔루션|로봇|시스템)\s*(?:의\s*)?(?:직접\s*)?(?:개발|구현|프로토타입)|"
    r"(?:모델|서비스|앱|웹|게임|솔루션)\s*(?:을|를)\s*(?:개발|구현)|"
    r"(?:앱|게임)\s*(?:제작|빌드|실행\s*파일)|실행\s*가능한\s*(?:웹|앱|게임)|"
    r"(?:로봇|자율주행)\s*(?:경진|프로그래밍)|"
    r"(?:API|클라우드|오픈\s*소스)\s*(?:개발|구현|경진)",
    re.IGNORECASE,
)
DEVELOPMENT = re.compile(
    BUILD_WORK.pattern + r"|해커톤|메이커톤|드래프톤|프롬프톤|데이터톤|코딩|알고리즘|"
    r"\b(?:hackathon|datathon|programming|coding|CTF)\b|"
    r"공공\s*데이터|빅\s*데이터|"
    r"(?:AI|인공지능|머신러닝|딥러닝)\s*[·: -]?\s*(?:에이전트|agent|모델|벤치마크)|"
    r"(?:정보|사이버)\s*보안",
    re.IGNORECASE,
)
TECH_TOPIC = re.compile(
    r"\b(?:AI|SW|IT|ICT|ML|LLM|API|AX|IoT)\b|인공지능|머신러닝|소프트웨어|"
    r"디지털|데이터|클라우드|개발자|컴퓨터|게임|로봇|자율주행|핀테크|정보보안|사이버보안|"
    r"웹[ /·]|앱[ /·]|서비스\s*기획|프로토타입",
    re.IGNORECASE,
)
TECH_CATEGORY = re.compile(
    r"\b(?:IT|SW|ICT|AI)\b|게임|소프트웨어|웹[ /·]|데이터|과학[ /•·]공학|학문[ /•·]과학",
    re.IGNORECASE,
)
CREATIVE = re.compile(
    r"숏\s*(?:폼|츠|드라마)|쇼츠|UCC|뮤직|BGM|영상|사진|웹툰|그림책|시나리오|"
    r"마스코트|캐릭터|포스터\s*디자인|광고\s*(?:공모전|대상)|슬로건|네이밍|명칭|꿀팁|소문내기|구독",
    re.IGNORECASE,
)
PROGRAM = re.compile(r"수강생|교육생|부트캠프|설명회|특강|채용\s*공고|서포터즈|포럼|세미나|컨설팅|컨퍼런스|박람회")
COMPETITION = re.compile(r"공모|경진|챌린지|대회|해커톤|메이커톤|드래프톤|프롬프톤|데이터톤|hackathon", re.I)


def development_candidate(title, category=None):
    if not title:
        return True
    if PROGRAM.search(title) and not COMPETITION.search(title):
        return False
    if CREATIVE.search(title) and not BUILD_WORK.search(title):
        return False
    return bool(DEVELOPMENT.search(title) or TECH_TOPIC.search(title) or TECH_CATEGORY.search(category or ""))


def development_contest(title, category=None, description=""):
    return development_candidate(title, category) and bool(
        DEVELOPMENT.search(title or "") or BUILD_WORK.search(description or "")
    )
