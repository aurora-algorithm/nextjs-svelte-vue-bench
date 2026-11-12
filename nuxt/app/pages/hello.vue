<script setup>
import { ref } from 'vue';

const n = ref(0);
</script>

<template>
  <button @click="n++">Clicked {{ n }}</button>
</template>
