# T00 evidence excerpts

## Java suite summary
[INFO] Tests run: 6, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.351 s -- in com.resolveflow.spike.CrossLanguageHashIT
[INFO] Tests run: 9, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 21.33 s -- in com.resolveflow.spike.MySQLTransactionIT
[INFO] Tests run: 2, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 2.683 s -- in com.resolveflow.spike.RocketMqIT
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.124 s -- in com.resolveflow.spike.SentinelIT
[INFO] Tests run: 20, Failures: 0, Errors: 0, Skipped: 0
[INFO] BUILD SUCCESS

## Enforcer rules
[INFO] Rule 0: org.apache.maven.enforcer.rules.version.RequireJavaVersion passed
[INFO] Rule 1: org.apache.maven.enforcer.rules.version.RequireMavenVersion passed
[INFO] Rule 2: org.apache.maven.enforcer.rules.dependency.RequireReleaseDeps passed
[INFO] Rule 3: org.apache.maven.enforcer.rules.dependency.BannedDependencies passed
[INFO] Rule 2: org.apache.maven.enforcer.rules.dependency.RequireReleaseDeps passed
[INFO] Rule 3: org.apache.maven.enforcer.rules.dependency.BannedDependencies passed
[INFO] Rule 2: org.apache.maven.enforcer.rules.dependency.RequireReleaseDeps passed
[INFO] Rule 3: org.apache.maven.enforcer.rules.dependency.BannedDependencies passed
[INFO] BUILD SUCCESS

## Python suite

============================= 18 passed in 4.36s ==============================

## Frontend build
$ vue-tsc --noEmit && vite build
[36mvite v8.3.0 [32mbuilding client environment for production...[36m[39m
dist/index.html                 0.33 kB │ gzip:  0.24 kB
dist/assets/index-CFk0EGgD.js  61.87 kB │ gzip: 24.53 kB │ map: 535.98 kB
[32m✓ built in 103ms[39m

## uv lock
Using CPython 3.12.13
Resolved 71 packages in 5.33s
