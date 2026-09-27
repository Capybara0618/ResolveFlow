FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ARG JAR_FILE
COPY ${JAR_FILE} /app/service.jar
# The local core profile uses the published synthetic contract keys when no
# deployment key is injected. Copy only fixture corpora required by that path.
COPY contracts/fixtures /app/contracts/fixtures
COPY contracts/core/fixtures /app/contracts/core/fixtures
ENTRYPOINT ["java", "-jar", "/app/service.jar"]
