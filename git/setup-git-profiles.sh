c2j git set read --file git-read.yaml
c2j git set write --file git-write.yaml
printf '%s' read | jobdb config set git-profile-ro --value-file - --url "http://192.168.1.195:9047/" --tenant c2
printf '%s' write | jobdb config set git-profile-rw --value-file - --url "http://192.168.1.195:9047/" --tenant c2
