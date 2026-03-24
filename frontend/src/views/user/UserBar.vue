<script setup>
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { useGlobalState } from '../../store'
import { api } from '../../api'
import UserLogin from './UserLogin.vue'

const message = useMessage()

const {
    userSettings, userJwt
} = useGlobalState()

const { t } = useI18n({
    messages: {
        en: {
            currentUser: 'Current Login User',
            fetchUserSettingsError: 'Login password is invalid or account not exist, it may be network connection issue, please try again later.',
        },
        zh: {
            currentUser: '当前登录用户',
            fetchUserSettingsError: '登录状态已失效或账号不存在，也可能是网络连接异常，请稍后再试。',
        }
    }
});

onMounted(async () => {
    await api.getUserOpenSettings(message);
    if (!userSettings.value.user_id) await api.getUserSettings(message);
});
</script>

<template>
    <div>
        <n-card :bordered="false" embedded v-if="!userSettings.fetched">
            <n-skeleton style="height: 50vh" />
        </n-card>
        <div v-else-if="userSettings.user_email">
            <n-alert type="success" :show-icon="false" :bordered="false">
                <span>
                    <b>{{ t('currentUser') }} <b>{{ userSettings.user_email }}</b></b>
                </span>
            </n-alert>
        </div>
        <div v-else class="center">
            <n-card :bordered="false" embedded style="max-width: 600px;">
                <n-alert v-if="userJwt" type="warning" :show-icon="false" :bordered="false" closable>
                    <span>{{ t('fetchUserSettingsError') }}</span>
                </n-alert>
                <UserLogin />
            </n-card>
        </div>
    </div>
</template>

<style scoped>
.n-alert {
    margin-top: 10px;
    margin-bottom: 10px;
    text-align: center;
}

.center {
    display: flex;
    text-align: center;
    place-items: center;
    justify-content: center;
    margin: 20px;
}
</style>
